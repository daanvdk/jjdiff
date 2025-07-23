from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


type LineStatus = Literal["added", "deleted", "changed", "unchanged"]


@dataclass
class Line:
    old: str | None
    new: str | None

    @property
    def status(self) -> LineStatus:
        if self.old is None:
            return "added"
        elif self.new is None:
            return "deleted"
        elif self.old != self.new:
            return "changed"
        else:
            return "unchanged"


type ChangeStatus = Literal["added", "deleted", "changed"]
type ChangeType = Literal["file", "dir"]


@dataclass
class Change:
    path: Path
    status: ChangeStatus
    lines: list[Line] | None

    @property
    def type(self) -> ChangeType:
        if self.lines is None:
            return "dir"
        else:
            return "file"


def reverse_changes(changes: Sequence[Change]) -> Iterator[Change]:
    for change in reversed(changes):
        yield reverse_change(change)


def reverse_change(change: Change) -> Change:
    match change.status:
        case "added":
            reverse_status = "deleted"
        case "changed":
            reverse_status = "changed"
        case "deleted":
            reverse_status = "added"

    if change.lines is None:
        reverse_lines = None
    else:
        reverse_lines = [Line(line.new, line.old) for line in change.lines]

    return Change(change.path, reverse_status, reverse_lines)


def apply_changes(root: Path, changes: Iterable[Change]) -> None:
    for change in changes:
        apply_change(root, change)


def apply_change(root: Path, change: Change) -> None:
    path = root / change.path

    if change.lines is None:
        content = None
    else:
        content = "\n".join(line.new for line in change.lines if line.new is not None)

    match change.status:
        case "added":
            match change.type:
                case "file":
                    assert content is not None
                    _ = path.write_text(content)
                case "dir":
                    assert content is None
                    path.mkdir()

        case "changed":
            assert change.type == "file"
            assert content is not None
            _ = path.write_text(content)

        case "deleted":
            match change.type:
                case "file":
                    assert content == ""
                    path.unlink()
                case "dir":
                    assert content is None
                    path.rmdir()
