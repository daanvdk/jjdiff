from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
import heapq
from itertools import product
from pathlib import Path
import stat
from typing import override

from jjdiff.change import (
    Change,
    Rename,
    ChangeMode,
    AddFile,
    ModifyFile,
    DeleteFile,
    AddBinary,
    ModifyBinary,
    DeleteBinary,
    AddSymlink,
    ModifySymlink,
    DeleteSymlink,
    Line,
)


SIMILARITY_THRESHOLD = 0.6


@dataclass
class File:
    lines: list[str]
    is_exec: bool


@dataclass
class Binary:
    data: bytes
    is_exec: bool


@dataclass
class Symlink:
    to: Path


type Content = File | Binary | Symlink


def diff(old_root: Path, new_root: Path) -> list[Change]:
    old_contents = Contents(old_root)
    new_contents = Contents(new_root)
    return diff_contents(old_contents, new_contents)


class Contents(Mapping[Path, Content]):
    root: Path

    def __init__(self, root: Path):
        self.root = root.resolve()

    @override
    def __iter__(self) -> Iterator[Path]:
        for root, _, names in self.root.walk():
            for name in names:
                path = root / name
                if path.is_symlink() or path.is_file():
                    yield path.relative_to(self.root)

    @override
    def __len__(self):
        res = 0
        for _ in self:
            res += 1
        return res

    @override
    def __getitem__(self, path: Path) -> Content:
        full_path = self.root / path
        try:
            full_path.resolve().relative_to(self.root)
        except ValueError:
            raise KeyError(path)

        if full_path.is_symlink():
            return Symlink(full_path.readlink())

        elif full_path.is_file():
            is_exec = bool(full_path.stat().st_mode & stat.S_IXUSR)
            try:
                text = full_path.read_text()
            except ValueError:
                return Binary(full_path.read_bytes(), is_exec)
            else:
                return File(text.split("\n"), is_exec)

        else:
            raise KeyError(full_path)


def diff_contents(
    old: Mapping[Path, Content],
    new: Mapping[Path, Content],
) -> list[Change]:
    changes: list[Change] = []
    added: dict[Path, Content] = {}

    # Start with going through all new content and diffing if it also existed
    # in the old content, if not we add it to the added dict
    for path, new_content in new.items():
        old_content = old.get(path)

        if old_content is None:
            added[path] = new_content
            continue

        changes.extend(diff_content(path, old_content, new_content))

    # Now we look for all paths that are in old but not in new
    deleted: dict[Path, Content] = {}

    for path in old:
        if path not in new:
            deleted[path] = old[path]

    # Now we try to find renames between the old and new paths
    renames: list[tuple[float, Path, Path]] = []

    for (old_path, old_content), (new_path, new_content) in product(
        deleted.items(), added.items()
    ):
        similarity = get_content_similarity(old_content, new_content)
        if similarity >= SIMILARITY_THRESHOLD:
            heapq.heappush(renames, (-similarity, old_path, new_path))

    while renames:
        _, old_path, new_path = heapq.heappop(renames)

        # Skip if part of it was used in another rename that came first
        if old_path not in deleted or new_path not in added:
            continue

        old_content = deleted.pop(old_path)
        new_content = added.pop(new_path)

        changes.append(Rename(old_path, new_path))
        changes.extend(diff_content(old_path, old_content, new_content))

    # All the rest we can delete/add
    for path, content in deleted.items():
        changes.append(delete_content(path, content))
    for path, content in added.items():
        changes.append(add_content(path, content))

    changes.sort(key=change_key)
    return changes


def change_key(change: Change) -> tuple[Path, int]:
    match change:
        case Rename(path):
            return (path, 0)
        case ChangeMode(path):
            return (path, 1)
        case DeleteFile(path) | DeleteBinary(path) | DeleteSymlink(path):
            return (path, 2)
        case ModifyFile(path) | ModifyBinary(path) | ModifySymlink(path):
            return (path, 3)
        case AddFile(path) | AddBinary(path) | AddSymlink(path):
            return (path, 4)


def diff_content(
    path: Path,
    old_content: Content,
    new_content: Content,
) -> Iterator[Change]:
    match old_content, new_content:
        case File(old_lines, old_is_exec), File(new_lines, new_is_exec):
            if old_is_exec != new_is_exec:
                yield ChangeMode(path, old_is_exec, new_is_exec)
            if old_lines != new_lines:
                yield ModifyFile(path, diff_lines(old_lines, new_lines))

        case Binary(old_data, old_is_exec), Binary(new_data, new_is_exec):
            if old_is_exec != new_is_exec:
                yield ChangeMode(path, old_is_exec, new_is_exec)
            if old_data != new_data:
                yield ModifyBinary(path, old_data, new_data)

        case Symlink(old_to), Symlink(new_to):
            if old_to != new_to:
                yield ModifySymlink(path, old_to, new_to)

        case _:
            yield delete_content(path, old_content)
            yield add_content(path, new_content)


def get_content_similarity(old_content: Content, new_content: Content) -> float:
    match old_content, new_content:
        case File(old_lines), File(new_lines):
            return get_similarity(old_lines, new_lines)
        case Binary(old_data), Binary(new_data):
            return get_similarity(old_data, new_data)
        case Symlink(old_to), Binary(new_to):
            return get_similarity(str(old_to), str(new_to))
        case _:
            return 0


def delete_content(path: Path, content: Content) -> Change:
    match content:
        case File(lines, is_exec):
            return DeleteFile(path, [Line(line, None) for line in lines], is_exec)
        case Binary(data, is_exec):
            return DeleteBinary(path, data, is_exec)
        case Symlink(to):
            return DeleteSymlink(path, to)


def add_content(path: Path, content: Content) -> Change:
    match content:
        case File(lines, is_exec):
            return AddFile(path, [Line(None, line) for line in lines], is_exec)
        case Binary(data, is_exec):
            return AddBinary(path, data, is_exec)
        case Symlink(to):
            return AddSymlink(path, to)


def get_similarity[T](old: Sequence[T], new: Sequence[T]) -> float:
    return SequenceMatcher(None, old, new).ratio()


def diff_lines(old: list[str], new: list[str]) -> list[Line]:
    min_cost: float = abs(len(old) - len(new))
    states: list[tuple[float, int, int, int, Line | None]] = [(min_cost, 0, 0, 0, None)]
    line_to: dict[tuple[int, int], Line | None] = {}

    while True:
        min_cost, _, old_index, new_index, line = heapq.heappop(states)

        if (old_index, new_index) in line_to:
            continue
        line_to[(old_index, new_index)] = line

        old_todo = len(old) - old_index
        new_todo = len(new) - new_index

        if not old_todo and not new_todo:
            lines: list[Line] = []

            while line is not None:
                lines.append(line)
                if line.old is not None:
                    old_index -= 1
                if line.new is not None:
                    new_index -= 1
                line = line_to[old_index, new_index]

            lines.reverse()
            return lines

        if old_todo:
            heapq.heappush(
                states,
                (
                    # If we have more old_todo than new_todo the change to
                    # the heuristic and the cost cancel eachother out,
                    # otherwise they add up and thus get a cost of 2.
                    min_cost + 2 * int(old_todo <= new_todo),
                    2,
                    old_index + 1,
                    new_index,
                    Line(old[old_index], None),
                ),
            )

        if new_todo:
            heapq.heappush(
                states,
                (
                    # If we have more new_todo than old_todo the change to
                    # the heuristic and the cost cancel eachother out,
                    # otherwise they add up and thus get a cost of 2.
                    min_cost + 2 * int(new_todo <= old_todo),
                    1,
                    old_index,
                    new_index + 1,
                    Line(None, new[new_index]),
                ),
            )

        if old_todo and new_todo:
            old_line = old[old_index]
            new_line = new[new_index]
            similarity = get_similarity(old_line, new_line)

            if similarity >= SIMILARITY_THRESHOLD:
                heapq.heappush(
                    states,
                    (
                        min_cost + (1 - similarity),
                        0,
                        old_index + 1,
                        new_index + 1,
                        Line(old_line, new_line),
                    ),
                )
