from pathlib import Path
from typing import Literal

from jjdiff.tui.drawable import Drawable
from jjdiff.tui.rows import Rows
from jjdiff.tui.text import Text, TextColor, TextStyle


from ...change import (
    AddBinary,
    AddFile,
    AddSymlink,
    Change,
    ChangeMode,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Rename,
)
from .markers import SelectionMarker
from .styles import SELECTED_BG


type ChangeIncluded = Literal["full", "partial", "none"]


def render_change_title(
    change: Change,
    selected: bool,
    included: ChangeIncluded | None,
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
        case None:
            action_text = Text(f"\u258c {action} ", TextStyle(fg=fg, bg=bg))

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

    title = Text.join(texts)
    if selected:
        return Rows([SelectionMarker(), title])
    else:
        return title
