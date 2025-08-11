from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import heapq
from itertools import product
from pathlib import Path
import stat
from typing import override

from .change import (
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
from .config import path_deprioritized


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
        try:
            old_content = old[path]
        except KeyError:
            added[path] = new_content
        else:
            is_deprioritized = path_deprioritized(path)
            changes.extend(
                diff_content(path, old_content, new_content, is_deprioritized)
            )

    # Now we look for all paths that are in old but not in new
    deleted = {path: old[path] for path in old if path not in new}

    # Now we try to find renames between the old and new paths
    renames: list[tuple[float, Path, Path]] = []

    for (old_path, old_content), (new_path, new_content) in product(
        deleted.items(), added.items()
    ):
        similarity = get_content_similarity(old_content, new_content)
        if similarity >= SIMILARITY_THRESHOLD:
            heapq.heappush(renames, (-similarity, old_path, new_path))

    renamed: dict[Path, Path] = {}
    while renames:
        _, old_path, new_path = heapq.heappop(renames)

        # Skip if part of it was used in another rename that came first
        if old_path not in deleted or new_path not in added:
            continue

        old_content = deleted.pop(old_path)
        new_content = added.pop(new_path)

        is_deprioritized = path_deprioritized(new_path)
        changes.append(Rename(old_path, new_path, is_deprioritized))
        changes.extend(
            diff_content(old_path, old_content, new_content, is_deprioritized)
        )
        renamed[old_path] = new_path

    # All the rest we can delete/add
    for path, content in deleted.items():
        is_deprioritized = path_deprioritized(path)
        changes.append(delete_content(path, content, is_deprioritized))

    for path, content in added.items():
        is_deprioritized = path_deprioritized(path)
        changes.append(add_content(path, content, is_deprioritized))

    changes.sort(key=change_key)
    return changes


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

    return (change.is_deprioritized, path, priority)


def diff_content(
    path: Path,
    old_content: Content,
    new_content: Content,
    is_deprioritized: bool,
) -> Iterator[Change]:
    match old_content, new_content:
        case File(old_lines, old_is_exec), File(new_lines, new_is_exec):
            if old_is_exec != new_is_exec:
                yield ChangeMode(path, old_is_exec, new_is_exec, is_deprioritized)
            if old_lines != new_lines:
                yield ModifyFile(
                    path, diff_lines(old_lines, new_lines), is_deprioritized
                )

        case Binary(old_data, old_is_exec), Binary(new_data, new_is_exec):
            if old_is_exec != new_is_exec:
                yield ChangeMode(path, old_is_exec, new_is_exec, is_deprioritized)
            if old_data != new_data:
                yield ModifyBinary(path, old_data, new_data, is_deprioritized)

        case Symlink(old_to), Symlink(new_to):
            if old_to != new_to:
                yield ModifySymlink(path, old_to, new_to, is_deprioritized)

        case _:
            yield delete_content(path, old_content, is_deprioritized)
            yield add_content(path, new_content, is_deprioritized)


def get_content_similarity(old_content: Content, new_content: Content) -> float:
    match old_content, new_content:
        case File(old_lines), File(new_lines):
            return get_text_similarity(old_lines, new_lines)
        case Binary(old_data), Binary(new_data):
            return get_binary_similarity(old_data, new_data)
        case Symlink(old_to), Binary(new_to):
            return get_line_similarity(str(old_to), str(new_to))
        case _:
            return 0


def get_text_similarity(old_lines: list[str], new_lines: list[str]) -> float:
    old_counts = get_line_counts(old_lines)
    new_counts = get_line_counts(new_lines)

    total = old_counts.total() + new_counts.total()
    if total == 0:
        return 1

    common = (old_counts & new_counts).total()
    return common * 2 / total


def get_line_counts(lines: list[str]) -> Counter[str]:
    counts = Counter[str]()

    for line in lines:
        line = line.strip()
        if line:
            counts[line] += 1

    return counts


def get_binary_similarity(old_data: bytes, new_data: bytes) -> float:
    old_chunks = set(map(stable_hash, get_binary_chunks(old_data)))
    new_chunks = set(map(stable_hash, get_binary_chunks(new_data)))

    total = len(old_chunks) + len(new_chunks)
    if total == 0:
        return 1

    common = len(old_chunks & new_chunks)
    return common * 2 / total


WINDOW_SIZE = 48
WINDOW_MASK = (1 << 12) - 1

HASH_BASE = 263
HASH_MODULUS = (1 << 31) - 1
HASH_BASE_POWER = pow(HASH_BASE, WINDOW_SIZE, HASH_MODULUS)


def get_binary_chunks(data: bytes) -> Iterator[bytes]:
    if len(data) <= WINDOW_SIZE:
        yield data
        return

    curr_hash = 0
    for i in range(WINDOW_SIZE):
        curr_hash = (curr_hash * HASH_BASE + data[i]) % HASH_MODULUS

    start = 0
    for i in range(WINDOW_SIZE, len(data)):
        if curr_hash & WINDOW_MASK == 0:
            yield data[start:i]
            start = i

        old_byte = data[i - WINDOW_SIZE]
        new_byte = data[i]

        curr_hash = (
            curr_hash - (old_byte * HASH_BASE_POWER) % HASH_MODULUS
        ) % HASH_MODULUS
        curr_hash = (curr_hash * HASH_BASE + new_byte) % HASH_MODULUS

    if start < len(data):
        yield data[start:]


def stable_hash(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=8).digest()


def delete_content(path: Path, content: Content, is_deprioritized: bool) -> Change:
    match content:
        case File(lines, is_exec):
            return DeleteFile(
                path, [Line(line, None) for line in lines], is_exec, is_deprioritized
            )
        case Binary(data, is_exec):
            return DeleteBinary(path, data, is_exec, is_deprioritized)
        case Symlink(to):
            return DeleteSymlink(path, to, is_deprioritized)


def add_content(path: Path, content: Content, is_deprioritized: bool) -> Change:
    match content:
        case File(lines, is_exec):
            return AddFile(
                path, [Line(None, line) for line in lines], is_exec, is_deprioritized
            )
        case Binary(data, is_exec):
            return AddBinary(path, data, is_exec, is_deprioritized)
        case Symlink(to):
            return AddSymlink(path, to, is_deprioritized)


def get_line_similarity(old: str, new: str) -> float:
    if old == new:
        return 1
    else:
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
            similarity = get_line_similarity(old_line, new_line)

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
