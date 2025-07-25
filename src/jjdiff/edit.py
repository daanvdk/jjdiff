from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from difflib import SequenceMatcher
import os
from pathlib import Path
import signal
import sys
import termios
import tty
from types import FrameType
from typing import Literal, cast, override

from .keyboard import Keyboard
from .change import (
    FILE_CHANGE_TYPES,
    AddBinary,
    AddFile,
    AddSymlink,
    Change,
    ChangeRef,
    ChangeMode,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    FileChange,
    Ref,
    Line,
    LineRef,
    LineStatus,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Rename,
    filter_changes,
)
from .drawable import Drawable
from .rows import Rows
from .fill import Fill
from .text import Text, TextColor, TextStyle
from .grid import Grid


STATUS_COLOR: Mapping[LineStatus, TextColor] = {
    "added": "green",
    "changed": "yellow",
    "deleted": "red",
    "unchanged": "default",
}
SELECTED_FG: Mapping[bool, TextColor] = {
    True: "white",
    False: "bright black",
}
SELECTED_BG: Mapping[bool, TextColor | None] = {
    True: "bright black",
    False: None,
}
BLOCK: Mapping[tuple[bool, bool], str] = {
    (False, False): " ",
    (False, True): "\u2584",
    (True, False): "\u2580",
    (True, True): "\u2588",
}
EDGE_PADDING = 5


@dataclass
class ChangeCursor:
    change: int

    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    def is_title_selected(self, change: int) -> bool:
        return self.change == change

    def is_line_selected(self, change: int, _line: int) -> bool:
        return self.change == change

    def is_all_lines_selected(self, change: int) -> bool:
        return self.change == change


@dataclass
class HunkCursor:
    change: int
    start: int
    end: int

    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    def is_title_selected(self, _change: int) -> bool:
        return False

    def is_line_selected(self, change: int, line: int) -> bool:
        return self.change == change and self.start <= line < self.end

    def is_all_lines_selected(self, _change: int) -> bool:
        return False


@dataclass
class LineCursor:
    change: int
    line: int

    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    def is_title_selected(self, _change: int) -> bool:
        return False

    def is_line_selected(self, change: int, line: int) -> bool:
        return self.change == change and self.line == line

    def is_all_lines_selected(self, _change: int) -> bool:
        return False


type Cursor = ChangeCursor | HunkCursor | LineCursor


class Action(ABC):
    @abstractmethod
    def apply(self, editor: "Editor") -> None:
        raise NotImplementedError

    @abstractmethod
    def revert(self, editor: "Editor") -> None:
        raise NotImplementedError


class AddIncludes(Action):
    refs: set[Ref]

    def __init__(self, refs: set[Ref]):
        self.refs = refs

    @override
    def apply(self, editor: "Editor") -> None:
        editor.included |= self.refs

    @override
    def revert(self, editor: "Editor") -> None:
        editor.included -= self.refs


class RemoveIncludes(Action):
    refs: set[Ref]

    def __init__(self, refs: set[Ref]):
        self.refs = refs

    @override
    def apply(self, editor: "Editor") -> None:
        editor.included -= self.refs

    @override
    def revert(self, editor: "Editor") -> None:
        editor.included |= self.refs


class Editor:
    changes: Sequence[Change]

    included: set[Ref]
    include_dependencies: dict[Ref, set[Ref]]
    include_dependants: dict[Ref, set[Ref]]

    opened: set[ChangeRef]

    undo_stack: list[tuple[Action, set[ChangeRef], Cursor]]
    redo_stack: list[tuple[Action, set[ChangeRef], Cursor]]

    drawable: Drawable
    cursor: Cursor
    width: int
    height: int
    y: int
    lines: list[str]

    should_render: bool
    should_draw: bool
    should_exit: bool
    is_reading: bool
    result: Iterator[Change] | None

    def __init__(self, changes: Sequence[Change]):
        self.changes = changes

        self.included = set()
        self.include_dependencies = {}
        self.include_dependants = {}
        self.add_dependencies()

        self.opened = set()

        self.undo_stack = []
        self.redo_stack = []

        self.drawable = Text("")
        self.cursor = ChangeCursor(0)
        self.width = 0
        self.height = 0
        self.y = 0
        self.lines = []

        self.should_render = True
        self.should_draw = True
        self.should_exit = False
        self.is_reading = False
        self.result = None

    def add_dependencies(self) -> None:
        self.add_delete_add_dependencies()
        self.add_line_dependencies()

    def add_delete_add_dependencies(self) -> None:
        # Add dependencies between deletes and adds on the same path
        deleted: dict[Path, Ref] = {}

        for change_index, change in enumerate(self.changes):
            match change:
                case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
                    deleted[path] = ChangeRef(change_index)

                case AddFile(path) | AddBinary(path) | AddSymlink(path):
                    try:
                        dependency = deleted[path]
                    except KeyError:
                        pass
                    else:
                        dependant = ChangeRef(change_index)
                        self.add_dependency(dependant, dependency)

                case _:
                    pass

    def add_line_dependencies(self) -> None:
        # Add dependencies between changes and lines in changes
        for change_index, change in enumerate(self.changes):
            match change:
                case AddFile(_, lines):
                    # All lines in an added file depend on the file being added
                    change_ref = ChangeRef(change_index)
                    for line_index in range(len(lines)):
                        line_ref = LineRef(change_index, line_index)
                        self.add_dependency(line_ref, change_ref)

                case DeleteFile(_, lines):
                    # A deleted file depends on all lines being deleted
                    change_ref = ChangeRef(change_index)
                    for line_index in range(len(lines)):
                        line_ref = LineRef(change_index, line_index)
                        self.add_dependency(change_ref, line_ref)

                case _:
                    pass

    def add_dependency(self, dependant: Ref, dependency: Ref) -> None:
        self.include_dependencies.setdefault(dependant, set()).add(dependency)
        self.include_dependants.setdefault(dependency, set()).add(dependant)

    def get_cursor_range(self, width: int) -> tuple[int, int]:
        # Add all changes up to the cursor to get the start line
        changes: list[Change] = []

        match self.cursor:
            case ChangeCursor(change):
                changes.extend(self.changes[:change])

            case HunkCursor(change, line) | LineCursor(change, line):
                changes.extend(self.changes[:change])
                match self.changes[change]:
                    case AddFile(path, lines, is_exec):
                        changes.append(AddFile(path, lines[:line], is_exec))
                    case ModifyFile(path, lines):
                        changes.append(ModifyFile(path, lines[:line]))
                    case DeleteFile(path, lines, is_exec):
                        changes.append(DeleteFile(path, lines[:line], is_exec))
                    case _:
                        pass  # never happens

        cursor_start = render_changes(
            changes, self.cursor, self.included, self.opened
        ).height(width)

        # Add all changes in the cursor to get the end line
        match self.cursor:
            case ChangeCursor(change):
                changes.append(self.changes[change])

            case HunkCursor(change, start, end):
                partial_lines = cast(FileChange, changes[-1]).lines
                change_lines = cast(FileChange, self.changes[change]).lines
                partial_lines.extend(change_lines[start:end])

            case LineCursor(change, line):
                partial_lines = cast(FileChange, changes[-1]).lines
                change_lines = cast(FileChange, self.changes[change]).lines
                partial_lines.append(change_lines[line])

        cursor_end = render_changes(
            changes, self.cursor, self.included, self.opened
        ).height(width)

        return cursor_start, cursor_end

    def draw(self) -> None:
        render = self.should_render

        if render:
            self.should_render = False
            self.drawable = render_changes(
                self.changes, self.cursor, self.included, self.opened
            )

        width, self.height = os.get_terminal_size()

        if render or width != self.width:
            self.lines = list(self.drawable.render(width - 1))
            self.width = width

            start, end = self.get_cursor_range(width)

            # Base the y on this
            self.y = min(
                max(self.y, end + EDGE_PADDING - self.height),
                start - EDGE_PADDING,
            )
            self.y = max(min(self.y, len(self.lines) - self.height), 0)

        sys.stdout.write("\x1b[2J\x1b[H")
        for line in self.lines[self.y : self.y + self.height]:
            sys.stdout.write(line)
            sys.stdout.write("\x1b[1E")
        self.draw_scrollbar()
        sys.stdout.flush()

    def draw_scrollbar(self) -> None:
        blocks = self.height * 2
        start = round(self.y / len(self.lines) * blocks)
        end = round((self.y + self.height) / len(self.lines) * blocks)

        sys.stdout.write(f"\x1b[H\x1b[{self.width - 1}C")
        for i in range(0, blocks, 2):
            style = TextStyle(fg="bright black")
            block = BLOCK[start <= i < end, start <= i + 1 < end]
            sys.stdout.write(f"{style.style_code}{block}{style.reset_code}")
            sys.stdout.write("\x1b[1B")

    def rerender(self):
        self.should_draw = True
        self.should_render = True

    def redraw(self):
        self.should_draw = True

    def exit(self):
        self.should_exit = True

    def handle_key(self, key: str) -> None:
        match key:
            case "ctrl+c" | "ctrl+d" | "escape":
                self.exit()
            case "k" | "up" | "shift+tab":
                self.prev_cursor()
            case "j" | "down" | "tab":
                self.next_cursor()
            case "h" | "left":
                self.grow_cursor()
            case "l" | "right":
                self.shrink_cursor()
            case " ":
                self.select_cursor()
            case "enter":
                self.confirm()
            case "u":
                self.undo()
            case "U":
                self.redo()
            case _:
                pass

    def prev_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change_index):
                self.cursor = ChangeCursor((change_index - 1) % len(self.changes))
                self.rerender()

            case HunkCursor(change_index, start, end):
                while True:
                    change = cast(FileChange, self.changes[change_index])

                    # Try to find the previous hunk end
                    end = start
                    while end > 0:
                        if change.lines[end - 1].status != "unchanged":
                            break
                        end -= 1
                    else:
                        # No hunk found, so go to the previous file change and
                        # try again
                        while True:
                            change_index = (change_index - 1) % len(self.changes)
                            prev_change = self.changes[change_index]
                            if ChangeRef(change_index) in self.opened and isinstance(
                                prev_change, FILE_CHANGE_TYPES
                            ):
                                change = prev_change
                                break

                        start = len(change.lines)
                        end = len(change.lines)
                        continue

                    # Find the start of the hunk
                    start = end - 1
                    while start > 0 and change.lines[start - 1].status != "unchanged":
                        start -= 1

                    self.cursor = HunkCursor(change_index, start, end)
                    self.rerender()
                    break

            case LineCursor(change_index, line):
                while True:
                    change = cast(FileChange, self.changes[change_index])

                    # Try to find the previous line
                    while line > 0:
                        line -= 1
                        if change.lines[line].status != "unchanged":
                            break
                    else:
                        # No line found, so go to the previous file change and
                        # try again
                        while True:
                            change_index = (change_index - 1) % len(self.changes)
                            prev_change = self.changes[change_index]
                            if ChangeRef(change_index) in self.opened and isinstance(
                                prev_change, FILE_CHANGE_TYPES
                            ):
                                change = prev_change
                                break

                        line = len(change.lines)
                        continue

                    self.cursor = LineCursor(change_index, line)
                    self.rerender()
                    break

    def next_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change_index):
                self.cursor = ChangeCursor((change_index + 1) % len(self.changes))
                self.rerender()

            case HunkCursor(change_index, start, end):
                while True:
                    change = cast(FileChange, self.changes[change_index])

                    # Try to find the next hunk start
                    start = end
                    while start < len(change.lines):
                        if change.lines[start].status != "unchanged":
                            break
                        start += 1
                    else:
                        # No hunk found, so go to the next file change and
                        # try again
                        while True:
                            change_index = (change_index + 1) % len(self.changes)
                            next_change = self.changes[change_index]
                            if ChangeRef(change_index) in self.opened and isinstance(
                                next_change, FILE_CHANGE_TYPES
                            ):
                                change = next_change
                                break

                        start = 0
                        end = 0
                        continue

                    # Find the end of the hunk
                    end = start + 1
                    while (
                        end < len(change.lines)
                        and change.lines[end].status != "unchanged"
                    ):
                        end += 1

                    self.cursor = HunkCursor(change_index, start, end)
                    self.rerender()
                    break

            case LineCursor(change_index, line):
                while True:
                    change = cast(FileChange, self.changes[change_index])

                    # Try to find the next line
                    while line < len(change.lines) - 1:
                        line += 1
                        if change.lines[line].status != "unchanged":
                            break
                    else:
                        # No line found, so go to the next file change and
                        # try again
                        while True:
                            change_index = (change_index + 1) % len(self.changes)
                            next_change = self.changes[change_index]
                            if ChangeRef(change_index) in self.opened and isinstance(
                                next_change, FILE_CHANGE_TYPES
                            ):
                                change = next_change
                                break

                        line = -1
                        continue

                    self.cursor = LineCursor(change_index, line)
                    self.rerender()
                    break

    def grow_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change_index):
                change_ref = ChangeRef(change_index)

                if change_ref in self.opened:
                    self.opened.remove(change_ref)
                    self.rerender()

            case HunkCursor(change_index):
                self.cursor = ChangeCursor(change_index)
                self.rerender()

            case LineCursor(change_index, line):
                change = cast(FileChange, self.changes[change_index])

                # Find hunk start
                start = line
                while start > 0 and change.lines[start - 1].status != "unchanged":
                    start -= 1

                # Find hunk end
                end = line + 1
                while (
                    end < len(change.lines) and change.lines[end].status != "unchanged"
                ):
                    end += 1

                self.cursor = HunkCursor(change_index, start, end)
                self.rerender()

    def shrink_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change_index):
                change_ref = ChangeRef(change_index)

                if change_ref not in self.opened:
                    self.opened.add(change_ref)
                    self.rerender()
                    return

                change = self.changes[change_index]
                if not isinstance(change, FILE_CHANGE_TYPES):
                    return

                # Find start of first hunk
                start = 0
                while change.lines[start].status == "unchanged":
                    start += 1

                # Find end of hunk
                end = start + 1
                while (
                    end < len(change.lines) and change.lines[end].status != "unchanged"
                ):
                    end += 1

                self.cursor = HunkCursor(change_index, start, end)
                self.rerender()

            case HunkCursor(change, start):
                self.cursor = LineCursor(change, start)
                self.rerender()

            case LineCursor():
                pass

    def select_cursor(self) -> None:
        refs: set[Ref] = set()

        match self.cursor:
            case ChangeCursor(change_index):
                change = self.changes[change_index]
                refs.update(get_change_refs(change_index, change))

            case HunkCursor(change_index, start, end):
                for line_index in range(start, end):
                    refs.add(LineRef(change_index, line_index))

            case LineCursor(change_index, line_index):
                refs.add(LineRef(change_index, line_index))

        new_refs = refs - self.included

        if new_refs:
            # Ensure we also include all dependencies
            while dependencies := {
                dependency
                for dependant in refs
                for dependency in self.include_dependencies.get(dependant, set())
                if dependency not in new_refs
            }:
                new_refs.update(dependencies)

            # Remove dependencies that were already included
            new_refs.difference_update(self.included)

            self.apply_action(AddIncludes(new_refs))
        else:
            # Ensure we also include all dependants
            while dependants := {
                dependant
                for dependency in refs
                for dependant in self.include_dependants.get(dependency, set())
                if dependant not in refs
            }:
                refs.update(dependants)

            # Remove dependencies that are not included
            refs.intersection_update(self.included)

            self.apply_action(RemoveIncludes(refs))

        self.rerender()
        self.next_cursor()

    def undo(self) -> None:
        try:
            action, opened, cursor = self.undo_stack.pop()
        except IndexError:
            return

        self.redo_stack.append((action, self.opened, self.cursor))
        action.revert(self)
        self.opened = opened
        self.cursor = cursor
        self.rerender()

    def redo(self) -> None:
        try:
            action, opened, cursor = self.redo_stack.pop()
        except IndexError:
            return

        self.undo_stack.append((action, self.opened, self.cursor))
        action.apply(self)
        self.opened = opened
        self.cursor = cursor
        self.rerender()

    def confirm(self) -> None:
        self.result = filter_changes(self.included, self.changes)
        self.exit()

    def apply_action(self, action: Action) -> None:
        self.redo_stack.clear()
        self.undo_stack.append((action, self.opened.copy(), self.cursor))
        action.apply(self)

    def on_resize(self, _signal: int, _frame: FrameType | None) -> None:
        self.should_draw = True
        if self.is_reading:
            raise ReadCancelled()

    def on_interrupt(self, _signal: int, _frame: FrameType | None) -> None:
        self.should_exit = True
        if self.is_reading:
            raise ReadCancelled()


def edit_changes(changes: Sequence[Change]) -> Iterator[Change]:
    if not changes:
        return iter([])

    editor = Editor(changes)
    keyboard = Keyboard()

    with ExitStack() as stack:
        # setup resize signal
        prev_handler = signal.signal(signal.SIGWINCH, editor.on_resize)
        stack.callback(signal.signal, signal.SIGWINCH, prev_handler)

        # setup cbreak mode
        attrs = tty.setraw(sys.stdin)
        stack.callback(termios.tcsetattr, sys.stdin, termios.TCSADRAIN, attrs)

        # hide cursor and switch to alternative buffer
        write_and_flush("\x1b[?25l\x1b[?1049h")
        stack.callback(write_and_flush, "\x1b[?1049l\x1b[?25h")

        while not editor.should_exit:
            if editor.should_draw:
                editor.should_draw = False
                editor.draw()

            try:
                editor.is_reading = True
                try:
                    key = keyboard.get()
                finally:
                    editor.is_reading = False
            except ReadCancelled:
                pass
            else:
                editor.handle_key(key)

        if editor.result is None:
            sys.exit(1)
        else:
            return editor.result


def write_and_flush(content: str) -> None:
    sys.stdout.write(content)
    sys.stdout.flush()


class ReadCancelled(Exception):
    pass


MIN_CONTEXT = 3
MIN_OMITTED = 2


def render_changes(
    changes: Sequence[Change],
    cursor: Cursor,
    included: set[Ref],
    opened: set[ChangeRef],
) -> Drawable:
    drawables: list[Drawable] = []
    renames: dict[Path, Path] = {}

    for i, change in enumerate(changes):
        change_opened = ChangeRef(i) in opened

        drawables.append(
            render_change(i, change, cursor, included, change_opened, renames)
        )

        if change_opened:
            drawables.append(Text())

    return Rows(drawables)


def get_change_refs(change_index: int, change: Change) -> set[Ref]:
    refs: set[Ref] = set()

    # For modify file the change itself does nothing, just the lines matters
    if not isinstance(change, ModifyFile):
        refs.add(ChangeRef(change_index))

    # For file changes we care about the lines
    if isinstance(change, FILE_CHANGE_TYPES):
        for line_index in range(len(change.lines)):
            refs.add(LineRef(change_index, line_index))

    return refs


type ChangeIncluded = Literal["full", "partial", "none"]


def render_change(
    change_index: int,
    change: Change,
    cursor: Cursor,
    included: set[Ref],
    opened: bool,
    renames: dict[Path, Path],
) -> Drawable:
    change_refs = get_change_refs(change_index, change)

    change_included: ChangeIncluded
    if not (change_refs - included):
        change_included = "full"
    elif change_refs & included:
        change_included = "partial"
    else:
        change_included = "none"

    title = render_change_title(
        change,
        cursor.is_title_selected(change_index),
        change_included,
        renames,
    )

    if not opened:
        return title

    drawables = [title]

    match change:
        case Rename() | ChangeMode():
            pass

        case AddFile(_, lines) | ModifyFile(_, lines) | DeleteFile(_, lines):
            drawables.append(render_change_lines(change_index, lines, cursor, included))

        case AddBinary() | ModifyBinary() | DeleteBinary():
            drawables.append(render_binary(change_index, cursor))

        case AddSymlink(_, new_to):
            lines = [Line(None, str(new_to))]
            drawables.append(render_change_lines(change_index, lines, cursor))

        case ModifySymlink(old_to, new_to):
            lines = [Line(str(old_to), str(new_to))]
            drawables.append(render_change_lines(change_index, lines, cursor))

        case DeleteSymlink(old_to):
            lines = [Line(str(old_to), None)]
            drawables.append(render_change_lines(change_index, lines, cursor))

    return Rows(drawables)


def render_change_lines(
    change_index: int,
    lines: list[Line],
    cursor: Cursor,
    included: set[Ref] | None = None,
) -> Drawable:
    drawables: list[Drawable] = []
    ranges: list[tuple[int, int]] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1

        if line.status == "unchanged":
            continue

        start = max(index - MIN_CONTEXT, 0)

        while index < len(lines) and lines[index].status != "unchanged":
            index += 1

        end = min(index + MIN_CONTEXT, len(lines))

        if ranges and start - ranges[-1][1] < MIN_OMITTED:
            start, _ = ranges.pop()

        ranges.append((start, end))

    index = 0
    old_line = 1
    new_line = 1

    for start, end in ranges:
        if index < start:
            for line in lines[index:start]:
                if line.old is not None:
                    old_line += 1
                if line.new is not None:
                    new_line += 1

            drawables.append(
                render_omitted(
                    start - index,
                    cursor.is_all_lines_selected(change_index),
                )
            )
        else:
            assert index == start, repr(ranges)

        rows: list[tuple[Drawable, ...]] = []

        for line_index, line in enumerate(lines[start:end], start):
            selected = cursor.is_line_selected(change_index, line_index)
            if included is None:
                line_included = None
            else:
                line_included = LineRef(change_index, line_index) in included

            underline_old: list[tuple[int, int]] = []
            underline_new: list[tuple[int, int]] = []

            if line.old is not None and line.new is not None:
                for op, old_start, old_end, new_start, new_end in SequenceMatcher(
                    None, line.old, line.new
                ).get_opcodes():
                    if op == "delete" or op == "replace":
                        underline_old.append((old_start, old_end))
                    if op == "insert" or op == "replace":
                        underline_new.append((new_start, new_end))

            old_line_status: LineStatus
            new_line_status: LineStatus

            if line.status == "changed":
                old_line_status = "deleted"
                new_line_status = "added"
            else:
                old_line_status = line.status
                new_line_status = line.status

            rows.append(
                (
                    *render_line(
                        old_line,
                        old_line_status,
                        line.old,
                        selected,
                        line_included,
                        underline_old,
                    ),
                    *render_line(
                        new_line,
                        new_line_status,
                        line.new,
                        selected,
                        line_included,
                        underline_new,
                    ),
                )
            )

            if line.old is not None:
                old_line += 1
            if line.new is not None:
                new_line += 1

        drawables.append(Grid((None, 1, None, 1), rows))
        index = end

    if index < len(lines):
        drawables.append(
            render_omitted(
                len(lines) - index,
                cursor.is_all_lines_selected(change_index),
            )
        )

    return Rows(drawables)


def render_change_title(
    change: Change,
    selected: bool,
    included: ChangeIncluded,
    renames: dict[Path, Path],
) -> Drawable:
    fg: TextColor

    match change:
        case Rename(path):
            action = "rename"
            file_type = "path"
            fg = "blue"

        case ChangeMode(path):
            action = "change mode"
            file_type = "file"
            fg = "blue"

        case AddFile(path):
            action = "add"
            file_type = "file"
            fg = "green"

        case AddBinary(path):
            action = "add"
            file_type = "file"
            fg = "green"

        case AddSymlink(path):
            action = "add"
            file_type = "symlink"
            fg = "green"

        case ModifyFile(path):
            action = "modify"
            file_type = "file"
            fg = "yellow"

        case ModifyBinary(path):
            action = "modify"
            file_type = "file"
            fg = "yellow"

        case ModifySymlink(path):
            action = "modify"
            file_type = "symlink"
            fg = "yellow"

        case DeleteFile(path):
            action = "delete"
            file_type = "file"
            fg = "red"

        case DeleteBinary(path):
            action = "delete"
            file_type = "file"
            fg = "red"

        case DeleteSymlink(path):
            action = "delete"
            file_type = "symlink"
            fg = "red"

    bg = SELECTED_BG[selected]

    if isinstance(change, Rename):
        renames[change.old_path] = change.new_path
    else:
        path = renames.get(path, path)

    match included:
        case "full":
            action_text = Text.join(
                [
                    Text(f" \u2713 {action}", TextStyle(fg="black", bg=fg, bold=True)),
                    Text("\u258c", TextStyle(fg=fg, bg=bg)),
                ]
            )
        case "partial":
            action_text = Text.join(
                [
                    Text(f" \u2212 {action}", TextStyle(fg="black", bg=fg, bold=True)),
                    Text("\u258c", TextStyle(fg=fg, bg=bg)),
                ]
            )
        case "none":
            action_text = Text(f"\u258c\u2717 {action} ", TextStyle(fg=fg, bg=bg))

    texts = [
        action_text,
        Text(f"{file_type} ", TextStyle(bg=bg, bold=included != "none")),
        Text(str(path), TextStyle(fg="blue", bg=bg, bold=included != "none")),
    ]

    if isinstance(change, Rename):
        texts.append(Text(" to ", TextStyle(bg=bg, bold=included != "none")))
        texts.append(
            Text(
                str(change.new_path),
                TextStyle(fg="blue", bg=bg, bold=included != "none"),
            )
        )

    return Text.join(texts)


def render_omitted(lines: int, selected: bool) -> Drawable:
    if lines == 1:
        plural = ""
    else:
        plural = "s"

    fg = SELECTED_FG[selected]
    bg = SELECTED_BG[selected]

    return Grid(
        (1, None, 1),
        [
            (
                Fill("\u2500", style=TextStyle(fg=fg, bg=bg)),
                Text(
                    f" omitted {lines} unchanged line{plural} ",
                    style=TextStyle(fg="white", bg=bg),
                ),
                Fill("\u2500", style=TextStyle(fg=fg, bg=bg)),
            )
        ],
    )


def render_line(
    line: int,
    status: LineStatus,
    content: str | None,
    selected: bool,
    included: bool | None,
    underline: list[tuple[int, int]],
) -> tuple[Drawable, Drawable]:
    gutter: Drawable
    drawable: Drawable

    if content is None:
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text("\u258f" + "\u2571" * 6, TextStyle(fg=fg, bg=bg))
        drawable = Fill("\u2571", TextStyle(fg=fg, bg=bg))

    elif status == "unchanged":
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258f {line:>4} ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(bg=bg))

    elif included is True:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text.join(
            [
                Text(f" \u2713{line:>4}", TextStyle(fg="black", bg=fg, bold=True)),
                Text("\u258c", TextStyle(fg=fg, bg=bg)),
            ]
        )

        drawable = render_line_content(
            content,
            underline,
            TextStyle(fg=fg, bg=bg, bold=True, italic=True),
        )

    elif included is False:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258c\u2717{line:>4} ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(fg=fg, bg=bg))

    else:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258c {line:>4} ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(fg=fg, bg=bg))

    return gutter, drawable


def render_line_content(
    content: str,
    underline: list[tuple[int, int]],
    style: TextStyle,
) -> Text:
    underlined_style = style.update(underline=True)

    texts: list[Text] = []
    index = 0

    for start, end in underline:
        texts.append(Text(content[index:start], style))
        texts.append(Text(content[start:end], underlined_style))
        index = end
    texts.append(Text(content[index:], style))

    return Text.join(texts)


def render_binary(change_index: int, cursor: Cursor) -> Drawable:
    selected = cursor.is_all_lines_selected(change_index)

    fg = SELECTED_FG[selected]
    bg = SELECTED_BG[selected]

    line_style = TextStyle(fg=fg, bg=bg)
    text_style = TextStyle(fg="white", bg=bg)

    hor = Fill("\u2500", line_style)
    ver = Text("\u2502", line_style)

    top_left = Text("\u256d", line_style)
    top_right = Text("\u256e", line_style)
    bot_left = Text("\u2570", line_style)
    bot_right = Text("\u256f", line_style)

    text = Text("cannot display binary file", text_style)
    fill = Fill(" ", line_style)

    return Grid(
        (None, 1, None, 1, None),
        [
            (top_left, hor, hor, hor, top_right),
            (ver, fill, fill, fill, ver),
            (ver, fill, fill, fill, ver),
            (ver, fill, text, fill, ver),
            (ver, fill, fill, fill, ver),
            (ver, fill, fill, fill, ver),
            (bot_left, hor, hor, hor, bot_right),
        ],
    )
