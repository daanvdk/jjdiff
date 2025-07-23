from collections.abc import Iterator
from difflib import Differ, SequenceMatcher
from pathlib import Path
from typing import Literal, cast

from jjdiff.change import Change, Line


ROOT = Path(".")


def diff(old_root: Path, new_root: Path, path: Path = ROOT) -> Iterator[Change]:
    old = old_root / path
    new = new_root / path

    if old.is_file():
        if not new.is_file():
            yield from diff_delete(old_root, path)
            yield from diff_add(new_root, path)
            return

        lines = diff_lines(old.read_text(), new.read_text())

        if any(line.status != "unchanged" for line in lines):
            yield Change(path, "changed", lines)

    elif old.is_dir():
        if not old.is_dir():
            yield from diff_delete(old_root, path)
            yield from diff_add(new_root, path)
            return

        old_children = {child.name for child in old.iterdir()}
        new_children = {child.name for child in new.iterdir()}
        children = sorted(old_children | new_children)

        for child in children:
            yield from diff(old_root, new_root, path / child)

    else:
        yield from diff_delete(old_root, path)
        yield from diff_add(new_root, path)


def diff_delete(old_root: Path, path: Path) -> Iterator[Change]:
    old = old_root / path

    if old.is_file():
        old_lines = old.read_text().split("\n")
        lines = [Line(old_line, None) for old_line in old_lines]
        yield Change(path, "deleted", lines)

    elif old.is_dir():
        for child in old.iterdir():
            yield from diff_delete(old_root, path / child.name)
        yield Change(path, "deleted", None)

    else:
        assert not old.exists()


def diff_add(new_root: Path, path: Path) -> Iterator[Change]:
    new = new_root / path

    if new.is_file():
        new_lines = new.read_text().split("\n")
        lines = [Line(None, new_line) for new_line in new_lines]
        yield Change(path, "added", lines)

    elif new.is_dir():
        yield Change(path, "added", None)
        for child in new.iterdir():
            yield from diff_add(new_root, path / child.name)

    else:
        assert not new.exists()


def diff_lines(old: str, new: str) -> list[Line]:
    lines: list[Line] = []

    for line in Differ().compare(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
    ):
        code = cast(Literal[" ", "-", "+", "?"], line[0])
        line = line[2:].rstrip("\n")

        match code:
            case " ":
                lines.append(Line(line, line))
            case "-":
                lines.append(Line(line, None))
            case "+":
                if lines and lines[-1].new is None:
                    old_line = lines.pop().old
                else:
                    old_line = None
                lines.append(Line(old_line, line))
            case "?":
                pass

    return lines
