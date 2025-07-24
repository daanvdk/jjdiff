import argparse
from pathlib import Path
from typing import cast

from .change import apply_changes, reverse_changes
from .diff import diff
from .edit import edit_changes


parser = argparse.ArgumentParser()
parser.add_argument("old", type=Path)
parser.add_argument("new", type=Path)


def main() -> None:
    args = parser.parse_args()
    old = cast(Path, args.old)
    new = cast(Path, args.new)

    new.joinpath("JJ-INSTRUCTIONS").unlink()

    changes = tuple(diff(old, new))
    apply_changes(new, reverse_changes(changes))
    apply_changes(new, edit_changes(changes))
