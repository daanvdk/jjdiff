import argparse
from pathlib import Path
from typing import cast

from .change import apply_changes, reverse_changes
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

    changes = tuple(diff(old, new))

    if only_print:
        render_changes(changes, None, None, None).print()
        return 0

    edited_changes = Editor(changes).run()
    if edited_changes is None:
        return 1

    apply_changes(new, reverse_changes(changes))
    apply_changes(new, edited_changes)
    return 0
