from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass
import dataclasses
from pathlib import Path
import shutil
import stat
from typing import Literal

from .deprioritize import is_path_deprioritized


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


@dataclass
class ChangeMode:
    path: Path
    old_is_exec: bool
    new_is_exec: bool


@dataclass
class AddFile:
    path: Path
    lines: list[Line]
    is_exec: bool


@dataclass
class ModifyFile:
    path: Path
    lines: list[Line]


@dataclass
class DeleteFile:
    path: Path
    lines: list[Line]
    is_exec: bool


@dataclass
class AddBinary:
    path: Path
    content_path: Path
    is_exec: bool


@dataclass
class ModifyBinary:
    path: Path
    old_content_path: Path
    new_content_path: Path


@dataclass
class DeleteBinary:
    path: Path
    content_path: Path
    is_exec: bool


@dataclass
class AddSymlink:
    path: Path
    to: Path


@dataclass
class ModifySymlink:
    path: Path
    old_to: Path
    new_to: Path


@dataclass
class DeleteSymlink:
    path: Path
    to: Path


type FileChange = AddFile | ModifyFile | DeleteFile
type BinaryChange = AddBinary | ModifyBinary | DeleteBinary
type SymlinkChange = AddSymlink | ModifySymlink | DeleteSymlink
type Change = Rename | ChangeMode | FileChange | BinaryChange | SymlinkChange


FILE_CHANGE_TYPES = (AddFile, ModifyFile, DeleteFile)


def reverse_changes(changes: Iterable[Change]) -> Sequence[Change]:
    reversed_changes: list[Change] = []
    renames: dict[Path, Path] = {}

    for change in changes:
        match change:
            case Rename(old_path, new_path):
                reversed_changes.append(Rename(new_path, old_path))
                renames[old_path] = new_path

            case ChangeMode(path, old_is_exec, new_is_exec):
                path = renames.get(path, path)
                reversed_changes.append(ChangeMode(path, new_is_exec, old_is_exec))

            case AddFile(path, lines, is_exec):
                path = renames.get(path, path)
                reversed_changes.append(DeleteFile(path, reverse_lines(lines), is_exec))

            case ModifyFile(path, lines):
                path = renames.get(path, path)
                reversed_changes.append(ModifyFile(path, reverse_lines(lines)))

            case DeleteFile(path, lines, is_exec):
                path = renames.get(path, path)
                reversed_changes.append(AddFile(path, reverse_lines(lines), is_exec))

            case AddBinary(path, content_path, is_exec):
                path = renames.get(path, path)
                reversed_changes.append(DeleteBinary(path, content_path, is_exec))

            case ModifyBinary(path, old_content_path, new_content_path):
                path = renames.get(path, path)
                reversed_changes.append(
                    ModifyBinary(path, new_content_path, old_content_path)
                )

            case DeleteBinary(path, content_path, is_exec):
                path = renames.get(path, path)
                reversed_changes.append(AddBinary(path, content_path, is_exec))

            case AddSymlink(path, to):
                path = renames.get(path, path)
                reversed_changes.append(DeleteSymlink(path, to))

            case ModifySymlink(path, old_to, new_to):
                path = renames.get(path, path)
                reversed_changes.append(ModifySymlink(path, new_to, old_to))

            case DeleteSymlink(path, to):
                path = renames.get(path, path)
                reversed_changes.append(AddSymlink(path, to))

    reversed_changes.sort(key=change_key)
    return reversed_changes


def change_key(change: Change) -> tuple[bool, Path, int]:
    match change:
        case Rename(path):
            priority = 0
        case ChangeMode(path):
            priority = 1
        case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
            priority = 2
        case ModifyFile(path) | ModifyBinary(path) | ModifySymlink(path):
            priority = 3
        case AddFile(path) | AddBinary(path) | AddSymlink(path):
            priority = 4

    return (is_change_deprioritized(change), path, priority)


def is_change_deprioritized(change: Change) -> bool:
    if isinstance(change, Rename):
        return is_path_deprioritized(change.new_path)
    else:
        return is_path_deprioritized(change.path)


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


def split_changes(
    changes: Iterable[Change],
    refs: Set[Ref],
) -> tuple[Sequence[Change], Sequence[Change]]:
    old_to_sel: list[Change] = []
    sel_to_new: list[Change] = []
    renames: dict[Path, Path] = {}

    for change_index, change in enumerate(changes):
        change_ref = ChangeRef(change_index)

        # For non file changes we just include the whole change or not
        if not isinstance(change, FILE_CHANGE_TYPES):
            if change_ref in refs:
                old_to_sel.append(change)
                if isinstance(change, Rename):
                    renames[change.old_path] = change.new_path
            else:
                if isinstance(change, Rename):
                    old_path = renames.get(change.old_path, change.old_path)
                    change = dataclasses.replace(change, old_path=old_path)
                else:
                    path = renames.get(change.path, change.path)
                    change = dataclasses.replace(change, path=path)
                sel_to_new.append(change)
            continue

        # Now that we know we have a file change, we first filter the lines
        old_to_sel_lines: list[Line] = []
        old_to_sel_lines_changed = False

        sel_to_new_lines: list[Line] = []
        sel_to_new_lines_changed = False

        for line_index, line in enumerate(change.lines):
            if line.status == "unchanged":
                old_to_sel_lines.append(line)
                sel_to_new_lines.append(line)

            elif LineRef(change_index, line_index) in refs:
                old_to_sel_lines.append(line)
                if line.new is not None:
                    sel_to_new_lines.append(Line(line.new, line.new))
                old_to_sel_lines_changed = True

            else:
                if line.old is not None:
                    old_to_sel_lines.append(Line(line.old, line.old))
                sel_to_new_lines.append(line)
                sel_to_new_lines_changed = True

        # Now we can check what the filtered change looks like
        match change:
            case AddFile(path, _, is_exec):
                if change_ref in refs:
                    old_to_sel.append(AddFile(path, old_to_sel_lines, is_exec))
                    if sel_to_new_lines_changed:
                        sel_path = renames.get(path, path)
                        sel_to_new.append(ModifyFile(sel_path, sel_to_new_lines))
                else:
                    assert not old_to_sel_lines
                    sel_path = renames.get(path, path)
                    sel_to_new.append(AddFile(sel_path, sel_to_new_lines, is_exec))

            case ModifyFile(path, _):
                if old_to_sel_lines_changed:
                    old_to_sel.append(ModifyFile(path, old_to_sel_lines))
                if sel_to_new_lines_changed:
                    sel_path = renames.get(path, path)
                    sel_to_new.append(ModifyFile(sel_path, sel_to_new_lines))

            case DeleteFile(path, _, is_exec):
                if change_ref in refs:
                    old_to_sel.append(DeleteFile(path, old_to_sel_lines, is_exec))
                    assert not sel_to_new_lines
                else:
                    if old_to_sel_lines_changed:
                        old_to_sel.append(ModifyFile(path, old_to_sel_lines))
                    sel_path = renames.get(path, path)
                    sel_to_new.append(DeleteFile(sel_path, sel_to_new_lines, is_exec))

    return old_to_sel, sel_to_new


def apply_changes(root: Path, changes: Iterable[Change]) -> None:
    for change in changes:
        apply_change(root, change)


def apply_change(root: Path, change: Change) -> None:
    renames: dict[Path, Path] = {}

    match change:
        case Rename(old_path, new_path):
            full_old_path = root / old_path
            full_new_path = root / new_path
            full_new_path.mkdir(exist_ok=True, parents=True)
            full_old_path.rename(full_new_path)

        case ChangeMode(path, _, is_exec):
            path = renames.get(path, path)
            full_path = root / path
            set_is_exec(full_path, is_exec)

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
                    write_lines(full_path, lines)
                case AddBinary(_, content_path) | ModifyBinary(_, _, content_path):
                    shutil.copyfile(content_path, full_path)
                case AddSymlink(_, to) | ModifySymlink(_, _, to):
                    full_path.symlink_to(to)

            if isinstance(change, (AddFile, AddBinary)) and change.is_exec:
                set_is_exec(full_path, True)

        case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
            path = renames.get(path, path)
            full_path = root / path

            full_path.unlink()

            full_path = full_path.parent
            while full_path != root and not any(full_path.iterdir()):
                full_path.relative_to(root)
                full_path.rmdir()
                full_path = full_path.parent


def write_lines(path: Path, lines: list[Line]) -> None:
    with path.open("w", newline="") as f:
        line_iter = (line.new for line in lines if line.new is not None)

        try:
            prev_line = next(line_iter)
        except StopIteration:
            return

        for line in line_iter:
            f.write(prev_line)
            f.write("\n")
            prev_line = line

        f.write(prev_line)


def set_is_exec(path: Path, is_exec: bool) -> None:
    mode = path.stat().st_mode
    if is_exec:
        mode |= stat.S_IXUSR
    else:
        mode &= ~stat.S_IXUSR
    path.chmod(mode)


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
