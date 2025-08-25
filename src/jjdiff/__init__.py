import argparse
from pathlib import Path
from typing import cast

from .change import apply_changes, reverse_changes, split_changes
from .diff import diff
from .editor import Editor
from .editor.render.changes import render_changes

parser = argparse.ArgumentParser()
parser.add_argument("--print", action="store_true")
parser.add_argument("old", type=Path)
parser.add_argument("new", type=Path)


def main() -> int:
    args = parser.parse_args()
    only_print = cast(bool, args.print)
    old = cast(Path, args.old)
    new = cast(Path, args.new)

    old_to_new = tuple(diff(old, new))

    if only_print:
        render_changes(old_to_new, None, None, None).print()
        return 0

    selection = Editor(old_to_new).run()

    if selection is None:
        return 1

    _, selected_to_new = split_changes(old_to_new, selection)
    new_to_selected = reverse_changes(selected_to_new)
    apply_changes(new, new_to_selected)

    return 0
