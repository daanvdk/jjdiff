from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
import stat
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


@dataclass
class Rename:
    old_path: Path
    new_path: Path
    is_deprioritized: bool


@dataclass
class ChangeMode:
    path: Path
    old_is_exec: bool
    new_is_exec: bool
    is_deprioritized: bool


@dataclass
class AddFile:
    path: Path
    lines: list[Line]
    is_exec: bool
    is_deprioritized: bool


@dataclass
class ModifyFile:
    path: Path
    lines: list[Line]
    is_deprioritized: bool


@dataclass
class DeleteFile:
    path: Path
    lines: list[Line]
    is_exec: bool
    is_deprioritized: bool


@dataclass
class AddBinary:
    path: Path
    data: bytes
    is_exec: bool
    is_deprioritized: bool


@dataclass
class ModifyBinary:
    path: Path
    old_data: bytes
    new_data: bytes
    is_deprioritized: bool


@dataclass
class DeleteBinary:
    path: Path
    data: bytes
    is_exec: bool
    is_deprioritized: bool


@dataclass
class AddSymlink:
    path: Path
    to: Path
    is_deprioritized: bool


@dataclass
class ModifySymlink:
    path: Path
    old_to: Path
    new_to: Path
    is_deprioritized: bool


@dataclass
class DeleteSymlink:
    path: Path
    to: Path
    is_deprioritized: bool


type FileChange = AddFile | ModifyFile | DeleteFile
type BinaryChange = AddBinary | ModifyBinary | DeleteBinary
type SymlinkChange = AddSymlink | ModifySymlink | DeleteSymlink
type Change = Rename | ChangeMode | FileChange | BinaryChange | SymlinkChange


FILE_CHANGE_TYPES = (AddFile, ModifyFile, DeleteFile)


def reverse_changes(changes: Sequence[Change]) -> Iterator[Change]:
    renames: dict[Path, Path] = {}
    for change in changes:
        if isinstance(change, Rename):
            renames[change.old_path] = change.new_path

    for change in reversed(changes):
        match change:
            case Rename(old_path, new_path, is_deprioritized):
                yield Rename(new_path, old_path, is_deprioritized)

            case ChangeMode(path, old_is_exec, new_is_exec, is_deprioritized):
                path = renames.get(path, path)
                yield ChangeMode(path, new_is_exec, old_is_exec, is_deprioritized)

            case AddFile(path, lines, is_exec, is_deprioritized):
                path = renames.get(path, path)
                yield DeleteFile(path, reverse_lines(lines), is_exec, is_deprioritized)

            case ModifyFile(path, lines, is_deprioritized):
                path = renames.get(path, path)
                yield ModifyFile(path, reverse_lines(lines), is_deprioritized)

            case DeleteFile(path, lines, is_exec, is_deprioritized):
                path = renames.get(path, path)
                yield AddFile(path, reverse_lines(lines), is_exec, is_deprioritized)

            case AddBinary(path, data, is_exec, is_deprioritized):
                path = renames.get(path, path)
                yield DeleteBinary(path, data, is_exec, is_deprioritized)

            case ModifyBinary(path, old_data, new_data, is_deprioritized):
                path = renames.get(path, path)
                yield ModifyBinary(path, new_data, old_data, is_deprioritized)

            case DeleteBinary(path, data, is_exec, is_deprioritized):
                path = renames.get(path, path)
                yield AddBinary(path, data, is_exec, is_deprioritized)

            case AddSymlink(path, to, is_deprioritized):
                path = renames.get(path, path)
                yield DeleteSymlink(path, to, is_deprioritized)

            case ModifySymlink(path, old_to, new_to, is_deprioritized):
                path = renames.get(path, path)
                yield ModifySymlink(path, new_to, old_to, is_deprioritized)

            case DeleteSymlink(path, to, is_deprioritized):
                path = renames.get(path, path)
                yield AddSymlink(path, to, is_deprioritized)


def reverse_lines(lines: list[Line]) -> list[Line]:
    return [Line(line.new, line.old) for line in lines]


@dataclass(frozen=True)
class ChangeRef:
    change: int


@dataclass(frozen=True)
class LineRef:
    change: int
    line: int


type Ref = ChangeRef | LineRef


def filter_changes(
    refs: set[Ref],
    changes: Iterable[Change],
) -> Iterator[Change]:
    for change_index, change in enumerate(changes):
        change_ref = ChangeRef(change_index)

        # For non file changes we just include the whole change or not
        if not isinstance(change, FILE_CHANGE_TYPES):
            if change_ref in refs:
                yield change
            continue

        # Now that we know we have a file change, we first filter the lines
        lines: list[Line] = []
        line_changes = False

        for line_index, line in enumerate(change.lines):
            line_ref = LineRef(change_index, line_index)
            if line_ref in refs:
                lines.append(line)
                line_changes = True
            elif line.old is not None:
                lines.append(Line(line.old, line.old))

        # Now we can check what the filtered change looks like
        match change:
            case AddFile(path, _, is_exec, is_deprioritized):
                if change_ref in refs:
                    yield AddFile(path, lines, is_exec, is_deprioritized)

            case ModifyFile(path, _, is_deprioritized):
                if line_changes:
                    yield ModifyFile(path, lines, is_deprioritized)

            case DeleteFile(path, _, is_exec, is_deprioritized):
                if change_ref in refs:
                    yield DeleteFile(path, lines, is_exec, is_deprioritized)
                elif line_changes:
                    yield ModifyFile(path, lines, is_deprioritized)


def apply_changes(root: Path, changes: Iterable[Change]) -> None:
    for change in changes:
        apply_change(root, change)


def apply_change(root: Path, change: Change) -> None:
    renames: dict[Path, Path] = {}

    match change:
        case Rename(old_path, new_path):
            full_old_path = root / old_path
            full_new_path = root / new_path
            full_old_path.rename(full_new_path)

        case ChangeMode(path, _, is_exec):
            path = renames.get(path, path)
            full_path = root / path

            mode = full_path.stat().st_mode
            if is_exec:
                mode |= stat.S_IXUSR
            else:
                mode &= ~stat.S_IXUSR
            full_path.chmod(mode)

        case (
            AddFile(path)
            | ModifyFile(path)
            | AddBinary(path)
            | ModifyBinary(path)
            | AddSymlink(path)
            | ModifySymlink(path)
        ):
            path = renames.get(path, path)
            full_path = root / path

            full_path.parent.mkdir(parents=True, exist_ok=True)

            match change:
                case AddFile(_, lines) | ModifyFile(_, lines):
                    full_path.write_text(lines_to_text(lines))
                case AddBinary(_, data) | ModifyBinary(_, _, data):
                    full_path.write_bytes(data)
                case AddSymlink(_, to) | ModifySymlink(_, _, to):
                    full_path.symlink_to(to)

            if isinstance(change, (AddFile, AddBinary)) and change.is_exec:
                mode = full_path.stat().st_mode
                mode |= stat.S_IXUSR
                full_path.chmod(mode)

        case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
            path = renames.get(path, path)
            full_path = root / path

            full_path.unlink()

            full_path = full_path.parent
            while full_path != root and not any(full_path.iterdir()):
                full_path.relative_to(root)
                full_path.rmdir()
                full_path = full_path.parent


def lines_to_text(lines: list[Line]) -> str:
    return "\n".join(line.new for line in lines if line.new is not None)


def get_change_refs(change_index: int, change: Change) -> set[Ref]:
    refs: set[Ref] = set()

    # For modify file the change itself does nothing, just the lines matters
    if not isinstance(change, ModifyFile):
        refs.add(ChangeRef(change_index))

    # For file changes we care about the lines
    if isinstance(change, FILE_CHANGE_TYPES):
        for line_index in range(len(change.lines)):
            refs.add(LineRef(change_index, line_index))

    return refs
