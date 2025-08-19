from jjdiff.tui.drawable import Drawable

from ..cursor import Cursor
from .change_textbox import render_change_textbox


def render_change_binary(change_index: int, cursor: Cursor | None) -> Drawable:
    return render_change_textbox(change_index, cursor, "cannot display binary file")
