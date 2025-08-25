import hashlib
import heapq
import mmap
import stat
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import product
from pathlib import Path
from typing import override

from .change import (
    AddBinary,
    AddFile,
    AddSymlink,
    Change,
    ChangeMode,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    Line,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Rename,
    change_key,
)

SIMILARITY_THRESHOLD = 0.6


@dataclass
class File:
    content_path: Path
    is_exec: bool


@dataclass
class Symlink:
    to: Path


type Content = File | Symlink


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

        if full_path.is_symlink():  # Symlink has to come first
            return Symlink(full_path.readlink())
        elif full_path.is_file():
            is_exec = bool(full_path.stat().st_mode & stat.S_IXUSR)
            return File(full_path, is_exec)
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
            changes.extend(diff_content(path, old_content, new_content))

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

        changes.append(Rename(old_path, new_path))
        changes.extend(diff_content(old_path, old_content, new_content))
        renamed[old_path] = new_path

    # All the rest we can delete/add
    for path, content in deleted.items():
        changes.append(delete_content(path, content))

    for path, content in added.items():
        changes.append(add_content(path, content))

    changes.sort(key=change_key)
    return changes


def diff_content(
    path: Path,
    old_content: Content,
    new_content: Content,
) -> Iterator[Change]:
    match old_content, new_content:
        case File(old_content_path, old_is_exec), File(new_content_path, new_is_exec):
            if content_is_equal(old_content_path, new_content_path):
                if old_is_exec != new_is_exec:
                    yield ChangeMode(path, old_is_exec, new_is_exec)
                return

            match split_lines(old_content_path), split_lines(new_content_path):
                case list(old_lines), list(new_lines):
                    if old_is_exec != new_is_exec:
                        yield ChangeMode(path, old_is_exec, new_is_exec)
                    lines = diff_lines(old_lines, new_lines)
                    if any(line.status != "unchanged" for line in lines):
                        yield ModifyFile(path, lines)

                case None, None:
                    if old_is_exec != new_is_exec:
                        yield ChangeMode(path, old_is_exec, new_is_exec)
                    yield ModifyBinary(path, old_content_path, new_content_path)

                case list(old_lines), None:
                    lines = [Line(line, None) for line in old_lines]
                    yield DeleteFile(path, lines, old_is_exec)
                    yield AddBinary(path, new_content_path, new_is_exec)

                case None, list(new_lines):
                    yield DeleteBinary(path, old_content_path, old_is_exec)
                    lines = [Line(None, line) for line in new_lines]
                    yield AddFile(path, lines, new_is_exec)

        case Symlink(old_to), Symlink(new_to):
            if old_to != new_to:
                yield ModifySymlink(path, old_to, new_to)

        case _:
            yield delete_content(path, old_content)
            yield add_content(path, new_content)


def content_is_equal(old_content: Path, new_content: Path) -> bool:
    # Different size is never equal
    if old_content.stat().st_size != new_content.stat().st_size:
        return False

    # Compare content through mmap
    with (
        old_content.open("rb") as old_file,
        new_content.open("rb") as new_file,
        mmap.mmap(old_file.fileno(), 0, access=mmap.ACCESS_READ) as old_data,
        mmap.mmap(new_file.fileno(), 0, access=mmap.ACCESS_READ) as new_data,
    ):
        return old_data == new_data


def get_content_similarity(old_content: Content, new_content: Content) -> float:
    match old_content, new_content:
        case File(old_content_path), File(new_content_path):
            if content_is_equal(old_content_path, new_content_path):
                return 1

            match split_lines(old_content_path), split_lines(new_content_path):
                case list(old_lines), list(new_lines):
                    return get_text_similarity(old_lines, new_lines)
                case None, None:
                    return get_binary_similarity(old_content_path, new_content_path)
                case _:
                    return 0

        case Symlink(old_to), Symlink(new_to):
            return get_line_similarity(str(old_to), str(new_to))

        case _:
            return 0


def split_lines(path: Path) -> list[str] | None:
    lines: list[str] = []
    trailing_newline = True

    try:
        with path.open("r", newline="") as f:
            for line in f:
                trailing_newline = line.endswith("\n")
                if trailing_newline:
                    line = line[:-1]
                lines.append(line)
    except UnicodeDecodeError:
        return None

    if trailing_newline:
        lines.append("")

    return lines


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


def get_binary_similarity(old_content_path: Path, new_content_path: Path) -> float:
    old_chunks = set(map(stable_hash, get_binary_chunks(old_content_path)))
    new_chunks = set(map(stable_hash, get_binary_chunks(new_content_path)))

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


def get_binary_chunks(path: Path) -> Iterator[memoryview]:
    with (
        path.open("rb") as file,
        mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as raw_data,
    ):
        # Wrap in memory view for zero copy chunks
        data = memoryview(raw_data)

        if len(data) <= WINDOW_SIZE:
            yield data
            return

        curr_hash = 0
        for i in range(WINDOW_SIZE):
            curr_hash = (curr_hash * HASH_BASE + data[i]) % HASH_MODULUS

        start = 0
        for i in range(WINDOW_SIZE, len(data)):
            if curr_hash & WINDOW_MASK == 0:
                chunk = data[start:i]
                yield chunk
                start = i

            old_byte = data[i - WINDOW_SIZE]
            new_byte = data[i]

            curr_hash = (
                curr_hash - (old_byte * HASH_BASE_POWER) % HASH_MODULUS
            ) % HASH_MODULUS
            curr_hash = (curr_hash * HASH_BASE + new_byte) % HASH_MODULUS

        if start < len(data):
            yield data[start:]


def stable_hash(data: memoryview) -> bytes:
    return hashlib.blake2b(data, digest_size=8).digest()


def delete_content(path: Path, content: Content) -> Change:
    match content:
        case File(content_path, is_exec):
            if old_lines := split_lines(content_path):
                lines = [Line(line, None) for line in old_lines]
                return DeleteFile(path, lines, is_exec)
            else:
                return DeleteBinary(path, content_path, is_exec)
        case Symlink(to):
            return DeleteSymlink(path, to)


def add_content(path: Path, content: Content) -> Change:
    match content:
        case File(content_path, is_exec):
            if new_lines := split_lines(content_path):
                lines = [Line(None, line) for line in new_lines]
                return AddFile(path, lines, is_exec)
            else:
                return AddBinary(path, content_path, is_exec)
        case Symlink(to):
            return AddSymlink(path, to)


def get_line_similarity(old: str, new: str) -> float:
    if old == new:
        return 1
    else:
        return SequenceMatcher(None, old, new).ratio()


def diff_lines(old: list[str], new: list[str]) -> list[Line]:
    start = 0
    while start < len(old) and start < len(new) and old[start] == new[start]:
        start += 1

    old_end = len(old)
    new_end = len(new)
    while old_end > start and new_end > start and old[old_end - 1] == new[new_end - 1]:
        old_end -= 1
        new_end -= 1

    lines = [Line(line, line) for line in old[:start]]
    lines.extend(diff_lines_base(old[start:old_end], new[start:new_end]))
    lines.extend(Line(line, line) for line in old[old_end:])
    return lines


def diff_lines_base(old: list[str], new: list[str]) -> list[Line]:
    min_cost = 100 * abs(len(old) - len(new))
    states: list[tuple[int, int, int, int, Line | None]] = [(min_cost, 0, 0, 0, None)]
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
                    min_cost + 200 * int(old_todo <= new_todo),
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
                    min_cost + 200 * int(new_todo <= old_todo),
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
                        # The cost scales with the similarity
                        # similarity 0 -> cost 200 (same as deletion + addition)
                        # similarity 1 -> cost   0 (no change)
                        min_cost + (200 - round(similarity * 200)),
                        0,
                        old_index + 1,
                        new_index + 1,
                        Line(old_line, new_line),
                    ),
                )
