from collections.abc import Mapping
from contextlib import ExitStack
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


class Editor:
    changes: list[Change]
    should_draw: bool
    should_exit: bool
    is_reading: bool
    result: list[Change] | None

    def __init__(self, changes: list[Change]):
        self.changes = changes
        self.should_draw = True
        self.should_exit = False
        self.is_reading = False
        self.result = None

    def draw(self) -> None:
        drawables: list[Drawable] = []

        for change in self.changes:
            if drawables:
                drawables.append(Text())
            drawables.append(render_change(change))

        drawable = Rows(drawables)

        width, height = os.get_terminal_size()
        sys.stdout.write("\x1b[2J\x1b[H")
        drawable.draw(width, height)
        sys.stdout.flush()

    def handle_key(self, key: str) -> None:
        match key:
            case "ctrl+c" | "ctrl+d" | "escape":
                self.should_exit = True

            case _:
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


def render_change(change: Change) -> Drawable:
    drawables = [render_change_title(change, False, False)]
    if change.lines is not None:
        drawables.append(render_change_lines(change.lines))
    return Rows(drawables)


def render_change_lines(lines: list[Line]) -> Drawable:
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

        if ranges and start - ranges[0][1] < MIN_OMITTED:
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

            drawables.append(render_omitted(start - index))

        rows: list[tuple[Drawable, ...]] = []

        for line in lines[start:end]:
            rows.append((
                *render_line(old_line, line.status, line.old, False, False),
                *render_line(new_line, line.status, line.new, False, False),
            ))
            if line.old is not None:
                old_line += 1
            if line.new is not None:
                new_line += 1

        drawables.append(Grid((None, 1, None, 1), rows))
        index = end

    if index < len(lines):
        drawables.append(render_omitted(len(lines) - index))

    return Rows(drawables)


def render_change_title(change: Change, selected: bool, toggled: bool) -> Drawable:
    fg = STATUS_COLOR[change.status]
    bg = SELECTED_BG[selected]

    if toggled:
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


def render_omitted(lines: int) -> Drawable:
    if lines == 1:
        plural = ""
    else:
        plural = "s"

    return Grid(
        (1, None, 1),
        [
            (
                Fill("\u2500", style=TextStyle(fg="bright black")),
                Text(
                    f" omitted {lines} unchanged line{plural} ",
                    style=TextStyle(fg="white"),
                ),
                Fill("\u2500", style=TextStyle(fg="bright black")),
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
