from collections.abc import Sequence
from pathlib import Path

from jjdiff.tui.drawable import Drawable
from jjdiff.tui.rows import Rows
from jjdiff.tui.text import Text

from ...change import (
    Change,
    ChangeRef,
    Ref,
)
from ..cursor import Cursor
from .change import render_change


def render_changes(
    changes: Sequence[Change],
    cursor: Cursor | None,
    included: set[Ref] | None,
    opened: set[ChangeRef] | None,
) -> Drawable:
    drawables: list[Drawable] = []
    renames: dict[Path, Path] = {}

    for i, change in enumerate(changes):
        change_opened = opened is None or ChangeRef(i) in opened

        drawables.append(
            render_change(i, change, cursor, included, change_opened, renames)
        )

        if change_opened:
            drawables.append(Text())

    return Rows(drawables)
