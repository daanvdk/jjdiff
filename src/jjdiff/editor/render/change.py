from pathlib import Path
from typing import Literal

from jjdiff.tui.drawable import Drawable
from jjdiff.tui.rows import Rows

from ...change import (
    AddBinary,
    AddFile,
    AddSymlink,
    Change,
    ChangeMode,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    Ref,
    Line,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Rename,
    get_change_refs,
)
from ..cursor import Cursor
from .change_title import render_change_title
from .change_file import render_change_file
from .change_binary import render_change_binary
from .change_deprioritized import render_change_deprioritized


type ChangeIncluded = Literal["full", "partial", "none"]


EXEC_LINE = {
    True: "File is executable",
    False: "File is not executable",
}


def render_change(
    change_index: int,
    change: Change,
    cursor: Cursor | None,
    included: set[Ref] | None,
    opened: bool,
    renames: dict[Path, Path],
) -> Drawable:
    change_refs = get_change_refs(change_index, change)

    change_included: ChangeIncluded | None
    if included is None:
        change_included = None
    elif not (change_refs - included):
        change_included = "full"
    elif change_refs & included:
        change_included = "partial"
    else:
        change_included = "none"

    title = render_change_title(
        change,
        cursor is not None and cursor.is_title_selected(change_index),
        change_included,
        renames,
    )

    if not opened:
        return title

    drawables = [title]

    match change:
        case Rename(old_path, new_path):
            lines = [Line(str(old_path), str(new_path))]
            drawables.append(
                render_change_file(change_index, lines, cursor, line_nums=False)
            )

        case ChangeMode(_, old_is_exec, new_is_exec):
            lines = [Line(EXEC_LINE[old_is_exec], EXEC_LINE[new_is_exec])]
            drawables.append(
                render_change_file(change_index, lines, cursor, line_nums=False)
            )

        case AddFile(_, lines) | ModifyFile(_, lines) | DeleteFile(_, lines):
            # Hide change for deprioritized files in print mode
            if cursor is None and change.is_deprioritized:
                drawables.append(render_change_deprioritized(change_index, cursor))
            else:
                drawables.append(
                    render_change_file(change_index, lines, cursor, included)
                )

        case AddBinary() | ModifyBinary() | DeleteBinary():
            drawables.append(render_change_binary(change_index, cursor))

        case AddSymlink(_, new_to):
            lines = [Line(None, str(new_to))]
            drawables.append(
                render_change_file(change_index, lines, cursor, line_nums=False)
            )

        case ModifySymlink(old_to, new_to):
            lines = [Line(str(old_to), str(new_to))]
            drawables.append(
                render_change_file(change_index, lines, cursor, line_nums=False)
            )

        case DeleteSymlink(old_to):
            lines = [Line(str(old_to), None)]
            drawables.append(
                render_change_file(change_index, lines, cursor, line_nums=False)
            )

    return Rows(drawables)
