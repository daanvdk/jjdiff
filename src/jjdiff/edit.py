from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
import termios
import tty
from types import FrameType
from typing import override

from .keyboard import Keyboard
from .change import Change, Line, LineStatus
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


@dataclass(frozen=True)
class ChangeInclude:
    change: int


@dataclass(frozen=True)
class LineInclude:
    change: int
    line: int


type Include = ChangeInclude | LineInclude


class Action(ABC):
    @abstractmethod
    def apply(self, editor: "Editor") -> None:
        raise NotImplementedError

    @abstractmethod
    def revert(self, editor: "Editor") -> None:
        raise NotImplementedError


class AddIncludes(Action):
    includes: set[Include]

    def __init__(self, includes: set[Include]):
        self.includes = includes

    @override
    def apply(self, editor: "Editor") -> None:
        editor.includes |= self.includes

    @override
    def revert(self, editor: "Editor") -> None:
        editor.includes -= self.includes


class RemoveIncludes(Action):
    includes: set[Include]

    def __init__(self, includes: set[Include]):
        self.includes = includes

    @override
    def apply(self, editor: "Editor") -> None:
        editor.includes -= self.includes

    @override
    def revert(self, editor: "Editor") -> None:
        editor.includes |= self.includes


class Editor:
    changes: list[Change]
    includes: set[Include]
    include_dependencies: dict[Include, set[Include]]
    include_dependants: dict[Include, set[Include]]

    should_render: bool
    should_draw: bool
    should_exit: bool
    is_reading: bool
    result: list[Change] | None

    drawable: Drawable
    width: int
    height: int
    y: int
    cursor: Cursor
    lines: list[str]

    undo_stack: list[tuple[Action, Cursor]]
    redo_stack: list[tuple[Action, Cursor]]

    def __init__(self, changes: list[Change]):
        self.changes = changes
        self.includes = set()
        self.include_dependencies = {}
        self.include_dependants = {}

        self.should_render = True
        self.should_draw = True
        self.should_exit = False
        self.is_reading = False
        self.result = None

        self.undo_stack = []
        self.redo_stack = []

        added: dict[Path, Include] = {}
        deleted: dict[Path, Include] = {}

        # Set dependencies
        for change_index, change in enumerate(self.changes):
            match change.status:
                case "added":
                    change_include = ChangeInclude(change_index)

                    # For a file or directory to be added its predecessor must be removed
                    if predecessor := deleted.pop(change.path, None):
                        self.add_dependency(change_include, predecessor)

                    # For a file or directory to be added its parent must be added
                    if parent := added.get(change.path.parent):
                        self.add_dependency(change_include, parent)

                    # For a line to be added the file must be added
                    for line_index, line in enumerate(change.lines or []):
                        assert line.status == "added"
                        line_include = LineInclude(change_index, line_index)
                        self.add_dependency(line_include, change_include)

                    added[change.path] = change_include

                case "changed":
                    pass

                case "deleted":
                    change_include = ChangeInclude(change_index)

                    # For a directory to be deleted all its children must be deleted
                    for child_path, child in deleted.items():
                        if child_path.parent == change.path:
                            self.add_dependency(change_include, child)

                    # For a file to be deleted all lines must be deleted
                    for line_index, line in enumerate(change.lines or []):
                        assert line.status == "deleted"
                        line_include = LineInclude(change_index, line_index)
                        self.add_dependency(change_include, line_include)

                    deleted[change.path] = change_include

        self.cursor = ChangeCursor(0)
        self.drawable = Text("")
        self.width = 0
        self.height = 0
        self.y = 0
        self.lines = []

    def add_dependency(self, dependant: Include, dependency: Include) -> None:
        self.include_dependencies.setdefault(dependant, set()).add(dependency)
        self.include_dependants.setdefault(dependency, set()).add(dependant)

    def draw(self) -> None:
        render = self.should_render

        if render:
            self.should_render = False
            self.drawable = render_changes(self.changes, self.cursor, self.includes)

        width, self.height = os.get_terminal_size()

        if render or width != self.width:
            self.lines = list(self.drawable.render(width - 1))
            self.width = width

            # Add all changes up to the cursor to get the start line
            changes: list[Change] = []

            match self.cursor:
                case ChangeCursor(change):
                    changes.extend(self.changes[:change])

                case HunkCursor(change, start, _end):
                    changes.extend(self.changes[:change])
                    selected_change = self.changes[change]
                    assert selected_change.lines is not None
                    changes.append(
                        Change(
                            selected_change.path,
                            selected_change.status,
                            selected_change.lines[:start],
                        )
                    )

                case LineCursor(change, line):
                    changes.extend(self.changes[:change])
                    selected_change = self.changes[change]
                    assert selected_change.lines is not None
                    changes.append(
                        Change(
                            selected_change.path,
                            selected_change.status,
                            selected_change.lines[:line],
                        )
                    )

            cursor_start = render_changes(changes, self.cursor, self.includes).height(
                width
            )

            # Add all changes in the cursor to get the end line
            match self.cursor:
                case ChangeCursor(change):
                    changes.append(self.changes[change])

                case HunkCursor(change, start, end):
                    selected_change = self.changes[change]
                    assert selected_change.lines is not None

                    partial_change = changes[-1]
                    assert partial_change.lines is not None

                    partial_change.lines.extend(selected_change.lines[start:end])

                case LineCursor(change, line):
                    selected_change = self.changes[change]
                    assert selected_change.lines is not None

                    partial_change = changes[-1]
                    assert partial_change.lines is not None

                    partial_change.lines.append(selected_change.lines[line])

            cursor_end = render_changes(changes, self.cursor, self.includes).height(
                width
            )

            # Base the y on this
            self.y = min(
                max(self.y, cursor_end + EDGE_PADDING - self.height),
                cursor_start - EDGE_PADDING,
            )
            self.y = min(max(self.y, 0), len(self.lines) - self.height)

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
            case "h" | "left":
                self.grow_cursor()
            case "j" | "down":
                self.next_cursor()
            case "k" | "up":
                self.prev_cursor()
            case "l" | "right":
                self.shrink_cursor()
            case " ":
                self.toggle_cursor()
            case "u":
                self.undo()
            case "U":
                self.redo()
            case "enter":
                self.commit()
            case _:
                raise Exception(f"unknown key: {key!r}")

    def prev_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change):
                self.cursor = ChangeCursor((change - 1) % len(self.changes))
                self.rerender()

            case HunkCursor(change, start, end):
                while True:
                    lines = self.changes[change].lines
                    assert lines is not None

                    end = start

                    while end > 0:
                        if lines[end - 1].status != "unchanged":
                            break
                        end -= 1
                    else:
                        while True:
                            change = (change - 1) % len(self.changes)
                            lines = self.changes[change].lines
                            if lines is not None:
                                break

                        start = len(lines)
                        end = len(lines)
                        continue

                    start = end - 1
                    while start > 0 and lines[start - 1].status != "unchanged":
                        start -= 1

                    self.cursor = HunkCursor(change, start, end)
                    self.rerender()
                    break

            case LineCursor(change, line):
                line -= 1

                while True:
                    lines = self.changes[change].lines
                    assert lines is not None

                    while line > 0:
                        if lines[line].status != "unchanged":
                            break
                        line -= 1
                    else:
                        while True:
                            change = (change - 1) % len(self.changes)
                            lines = self.changes[change].lines
                            if lines is not None:
                                break

                        line = len(lines) - 1
                        continue

                    self.cursor = LineCursor(change, line)
                    self.rerender()
                    break

    def next_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change):
                self.cursor = ChangeCursor((change + 1) % len(self.changes))
                self.rerender()

            case HunkCursor(change, start, end):
                while True:
                    lines = self.changes[change].lines
                    assert lines is not None

                    start = end

                    while start < len(lines):
                        if lines[start].status != "unchanged":
                            break
                        start += 1
                    else:
                        while True:
                            change = (change + 1) % len(self.changes)
                            if self.changes[change].lines is not None:
                                break

                        start = 0
                        end = 0
                        continue

                    end = start + 1
                    while end < len(lines) and lines[end].status != "unchanged":
                        end += 1

                    self.cursor = HunkCursor(change, start, end)
                    self.rerender()
                    break

            case LineCursor(change, line):
                line += 1

                while True:
                    lines = self.changes[change].lines
                    assert lines is not None

                    while line < len(lines):
                        if lines[line].status != "unchanged":
                            break
                        line += 1
                    else:
                        while True:
                            change = (change + 1) % len(self.changes)
                            if self.changes[change].lines is not None:
                                break

                        line = 0
                        continue

                    self.cursor = LineCursor(change, line)
                    self.rerender()
                    break

    def grow_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(_change):
                pass

            case HunkCursor(change, _start, _end):
                self.cursor = ChangeCursor(change)
                self.rerender()

            case LineCursor(change, line):
                lines = self.changes[change].lines
                assert lines is not None

                start = line
                while start > 0 and lines[start - 1].status != "unchanged":
                    start -= 1

                end = line + 1
                while end < len(lines) and lines[end].status != "unchanged":
                    end += 1

                self.cursor = HunkCursor(change, start, end)
                self.rerender()

    def shrink_cursor(self) -> None:
        match self.cursor:
            case ChangeCursor(change):
                lines = self.changes[change].lines
                if lines is None:
                    return

                start = 0
                while lines[start].status == "unchanged":
                    start += 1

                end = start + 1
                while end < len(lines) and lines[end].status != "unchanged":
                    end += 1

                self.cursor = HunkCursor(change, start, end)
                self.rerender()

            case HunkCursor(change, start, _):
                self.cursor = LineCursor(change, start)
                self.rerender()

            case LineCursor(_change, _line):
                pass

    def toggle_cursor(self) -> None:
        includes: set[Include] = set()

        match self.cursor:
            case ChangeCursor(change):
                if self.changes[change].status != "changed":
                    includes.add(ChangeInclude(change))

                lines = self.changes[change].lines
                if lines is not None:
                    for line in range(len(lines)):
                        includes.add(LineInclude(change, line))

            case HunkCursor(change, start, end):
                for line in range(start, end):
                    includes.add(LineInclude(change, line))

            case LineCursor(change, line):
                includes.add(LineInclude(change, line))

        new_includes = includes - self.includes

        if new_includes:
            # Ensure we also include all dependencies
            while dependencies := {
                dependency
                for include in new_includes
                for dependency in self.include_dependencies.get(include, set())
                if dependency not in new_includes
            }:
                new_includes.update(dependencies)

            # Remove dependencies that were already in the includes
            new_includes.difference_update(self.includes)

            self.apply_action(AddIncludes(new_includes))
        else:
            # Ensure we also include all dependants
            while dependants := {
                dependant
                for include in includes
                for dependant in self.include_dependants.get(include, set())
                if dependant not in includes
            }:
                includes.update(dependants)

            # Remove dependencies that are not in the includes
            includes.intersection_update(self.includes)

            self.apply_action(RemoveIncludes(includes))

        self.rerender()
        self.next_cursor()

    def undo(self) -> None:
        try:
            action, cursor = self.undo_stack.pop()
        except IndexError:
            return

        self.redo_stack.append((action, self.cursor))
        action.revert(self)
        self.cursor = cursor
        self.rerender()

    def redo(self) -> None:
        try:
            action, cursor = self.redo_stack.pop()
        except IndexError:
            return

        self.undo_stack.append((action, self.cursor))
        action.apply(self)
        self.cursor = cursor
        self.rerender()

    def commit(self) -> None:
        self.result = []

        for change_index, change in enumerate(self.changes):
            change_include = ChangeInclude(change_index)

            lines: list[Line] | None
            line_changes = False

            if change.lines is None:
                lines = None
            else:
                lines = []

                for line_index, line in enumerate(change.lines):
                    line_include = LineInclude(change_index, line_index)

                    if line_include in self.includes:
                        lines.append(line)
                        line_changes = True
                    elif line.old is not None:
                        lines.append(Line(line.old, line.old))

            match change.status:
                case "added":
                    if change_include in self.includes:
                        self.result.append(Change(change.path, "added", lines))

                case "changed":
                    if line_changes:
                        self.result.append(Change(change.path, "changed", lines))

                case "deleted":
                    if change_include in self.includes:
                        self.result.append(Change(change.path, "deleted", lines))
                    elif line_changes:
                        self.result.append(Change(change.path, "changed", lines))

        self.exit()

    def apply_action(self, action: Action) -> None:
        self.redo_stack.clear()
        self.undo_stack.append((action, self.cursor))
        action.apply(self)

    def on_resize(self, _signal: int, _frame: FrameType | None) -> None:
        self.should_draw = True
        if self.is_reading:
            raise ReadCancelled()

    def on_interrupt(self, _signal: int, _frame: FrameType | None) -> None:
        self.should_exit = True
        if self.is_reading:
            raise ReadCancelled()


def edit_changes(changes: list[Change]) -> list[Change]:
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
    changes: list[Change],
    cursor: Cursor,
    includes: set[Include],
) -> Drawable:
    drawables: list[Drawable] = []

    for i, change in enumerate(changes):
        if drawables:
            drawables.append(Text())
        drawables.append(render_change(i, change, cursor, includes))

    return Rows(drawables)


def render_change(
    change_index: int,
    change: Change,
    cursor: Cursor,
    includes: set[Include],
) -> Drawable:
    drawables = [
        render_change_title(
            change,
            cursor.is_title_selected(change_index),
            ChangeInclude(change_index) in includes,
        )
    ]

    if change.lines is not None:
        drawables.append(
            render_change_lines(
                change_index,
                change.lines,
                cursor,
                includes,
            )
        )

    return Rows(drawables)


def render_change_lines(
    change_index: int,
    lines: list[Line],
    cursor: Cursor,
    includes: set[Include],
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
            included = LineInclude(change_index, line_index) in includes

            rows.append((
                *render_line(old_line, line.status, line.old, selected, included),
                *render_line(new_line, line.status, line.new, selected, included),
            ))

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


def render_change_title(change: Change, selected: bool, included: bool) -> Drawable:
    fg = STATUS_COLOR[change.status]
    bg = SELECTED_BG[selected]

    if change.status == "changed":
        assert not included
        status_text = Text(f"\u258c  {change.status} ", TextStyle(fg=fg, bg=bg))
    elif included:
        status_text = Text.join([
            Text(f" \u2713 {change.status}", TextStyle(fg="black", bg=fg, bold=True)),
            Text("\u258c", TextStyle(fg=fg, bg=bg)),
        ])
    else:
        status_text = Text(f"\u258c\u2717 {change.status} ", TextStyle(fg=fg, bg=bg))

    return Text.join([
        status_text,
        Text(f"{change.type} ", TextStyle(bg=bg, bold=included)),
        Text(str(change.path), TextStyle(fg="blue", bg=bg, bold=included)),
    ])


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
    included: bool,
) -> tuple[Drawable, Drawable]:
    if content is None:
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text("\u258f" + "\u2571" * 6, TextStyle(fg=fg, bg=bg))
        drawable = Fill("\u2571", TextStyle(fg=fg, bg=bg))

    elif status == "unchanged":
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258f {line:>4} ", TextStyle(fg=fg, bg=bg))
        drawable = Text(content, TextStyle(bg=bg))

    elif included:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text.join([
            Text(f" \u2713{line:>4}", TextStyle(fg="black", bg=fg, bold=True)),
            Text("\u258c", TextStyle(fg=fg, bg=bg)),
        ])
        drawable = Text(content, TextStyle(fg=fg, bg=bg, bold=True, italic=True))

    else:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258c\u2717{line:>4} ", TextStyle(fg=fg, bg=bg))
        drawable = Text(content, TextStyle(fg=fg, bg=bg))

    return gutter, drawable