from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
import os
import signal
import sys
import termios
import tty
from types import FrameType

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

    def is_title_selected(self) -> bool:
        return True

    def is_line_selected(self, _line: int) -> bool:
        return True

    def is_all_lines_selected(self) -> bool:
        return True


@dataclass
class HunkCursor:
    change: int
    start: int
    end: int

    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    def is_title_selected(self) -> bool:
        return False

    def is_line_selected(self, line: int) -> bool:
        return self.start <= line < self.end

    def is_all_lines_selected(self) -> bool:
        return False


@dataclass
class LineCursor:
    change: int
    line: int

    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    def is_title_selected(self) -> bool:
        return False

    def is_line_selected(self, line: int) -> bool:
        return self.line == line

    def is_all_lines_selected(self) -> bool:
        return False


@dataclass
class NoCursor:
    def is_change_selected(self, _change: int) -> bool:
        return False

    def is_title_selected(self) -> bool:
        return False

    def is_line_selected(self, _line: int) -> bool:
        return False

    def is_all_lines_selected(self) -> bool:
        return False


type Cursor = ChangeCursor | HunkCursor | LineCursor | NoCursor


class Editor:
    changes: list[Change]
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

    def __init__(self, changes: list[Change]):
        self.changes = changes
        self.should_render = True
        self.should_draw = True
        self.should_exit = False
        self.is_reading = False
        self.result = None

        change = 0
        while change < len(changes):
            if changes[change].type != "file":
                change += 1
                continue

            lines = changes[change].lines
            assert lines is not None

            start = 0
            while lines[start].status == "unchanged":
                start += 1

            end = start
            while end < len(lines) and lines[end].status != "unchanged":
                end += 1

            self.cursor = HunkCursor(change, start, end)
            break
        else:
            self.cursor = ChangeCursor(0)

        self.drawable = Text("")
        self.width = 0
        self.height = 0
        self.y = 0
        self.lines = []

    def draw(self) -> None:
        render = self.should_render

        if render:
            self.should_render = False
            self.drawable = render_changes(self.changes, self.cursor)

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

                case NoCursor():
                    pass

            cursor_start = render_changes(changes, self.cursor).height(width)

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

                case NoCursor():
                    pass

            cursor_end = render_changes(changes, self.cursor).height(width)

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

            case "h":
                # grow cursor
                match self.cursor:
                    case ChangeCursor(_):
                        pass

                    case HunkCursor(change, _):
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

                    case NoCursor():
                        pass

            case "j":
                # next cursor
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

                    case NoCursor():
                        pass

            case "k":
                # prev cursor
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

                    case NoCursor():
                        pass
            case "l":
                # shrink cursor
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

                    case LineCursor(change, line):
                        pass

                    case NoCursor():
                        pass

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


def render_changes(changes: list[Change], cursor: Cursor) -> Drawable:
    drawables: list[Drawable] = []

    for i, change in enumerate(changes):
        if drawables:
            drawables.append(Text())

        if cursor.is_change_selected(i):
            change_cursor = cursor
        else:
            change_cursor = NoCursor()

        drawables.append(render_change(change, change_cursor))

    return Rows(drawables)


def render_change(change: Change, cursor: Cursor) -> Drawable:
    drawables = [render_change_title(change, cursor.is_title_selected(), False)]

    if change.lines is not None:
        drawables.append(render_change_lines(change.lines, cursor))

    return Rows(drawables)


def render_change_lines(lines: list[Line], cursor: Cursor) -> Drawable:
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
                render_omitted(start - index, cursor.is_all_lines_selected())
            )
        else:
            assert index == start, repr(ranges)

        rows: list[tuple[Drawable, ...]] = []

        for line_index, line in enumerate(lines[start:end], start):
            selected = cursor.is_line_selected(line_index)

            rows.append((
                *render_line(old_line, line.status, line.old, selected, False),
                *render_line(new_line, line.status, line.new, selected, False),
            ))

            if line.old is not None:
                old_line += 1
            if line.new is not None:
                new_line += 1

        drawables.append(Grid((None, 1, None, 1), rows))
        index = end

    if index < len(lines):
        drawables.append(
            render_omitted(len(lines) - index, cursor.is_all_lines_selected())
        )

    return Rows(drawables)


def render_change_title(change: Change, selected: bool, toggled: bool) -> Drawable:
    fg = STATUS_COLOR[change.status]
    bg = SELECTED_BG[selected]

    if change.status == "changed":
        assert not toggled
        status_text = Text(f"\u258c  {change.status} ", TextStyle(fg=fg, bg=bg))
    elif toggled:
        status_text = Text.join([
            Text(f" \u2713 {change.status}", TextStyle(fg="black", bg=fg, bold=True)),
            Text("\u258c", TextStyle(fg=fg, bg=bg)),
        ])
    else:
        status_text = Text(f"\u258c\u2717 {change.status} ", TextStyle(fg=fg, bg=bg))

    return Text.join([
        status_text,
        Text(f"{change.type} ", TextStyle(bg=bg, bold=toggled)),
        Text(str(change.path), TextStyle(fg="blue", bg=bg, bold=toggled)),
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
    toggled: bool,
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

    elif toggled:
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
