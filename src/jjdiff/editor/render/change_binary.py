from jjdiff.tui.drawable import Drawable
from jjdiff.tui.fill import Fill
from jjdiff.tui.text import Text, TextStyle
from jjdiff.tui.grid import Grid

from ..cursor import Cursor
from .styles import SELECTED_BG, SELECTED_FG


def render_change_binary(change_index: int, cursor: Cursor | None) -> Drawable:
    selected = cursor is not None and cursor.is_all_lines_selected(change_index)

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
