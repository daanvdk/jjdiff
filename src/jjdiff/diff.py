import hashlib
import heapq
import mmap
import stat
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import product
from pathlib import Path
from typing import Literal, override

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
SIMILARITY_MIN_RATIO = SIMILARITY_THRESHOLD / (2 - SIMILARITY_THRESHOLD)


def ratio(old_total: int, new_total: int) -> float:
    return min(old_total, new_total) / max(old_total, new_total)


@dataclass
class File:
    content_path: Path
    is_exec: bool


@dataclass
class Symlink:
    to: Path


type Content = File | Symlink
type ContentSummary = Counter[str] | frozenset[bytes] | str


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

    old_summaries = {
        path: get_content_summary(content) for path, content in deleted.items()
    }
    new_summaries = {
        path: get_content_summary(content) for path, content in added.items()
    }

    for (old_path, old_summary), (new_path, new_summary) in product(
        old_summaries.items(), new_summaries.items()
    ):
        similarity = get_summary_similarity(old_summary, new_summary)
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
    old_size = old_content.stat().st_size
    if old_size != new_content.stat().st_size:
        return False

    # Empty files are equal
    if old_size == 0:
        return True

    # Compare content through mmap
    with (
        old_content.open("rb") as old_file,
        new_content.open("rb") as new_file,
        mmap.mmap(old_file.fileno(), 0, access=mmap.ACCESS_READ) as old_data,
        mmap.mmap(new_file.fileno(), 0, access=mmap.ACCESS_READ) as new_data,
    ):
        return memoryview(old_data) == memoryview(new_data)


def get_content_summary(content: Content) -> ContentSummary:
    match content:
        case File(content_path, _):
            if lines := split_lines(content_path):
                return get_line_counts(lines)
            else:
                return frozenset(get_binary_chunks(content_path))
        case Symlink(to):
            return str(to)


def get_summary_similarity(old: ContentSummary, new: ContentSummary) -> float:
    match old, new:
        case Counter(), Counter():
            old_total = old.total()
            new_total = new.total()
            total = old_total + new_total

            if total == 0:
                return 1.0
            elif ratio(old_total, new_total) < SIMILARITY_MIN_RATIO:
                return 0.0
            else:
                return (old & new).total() * 2 / total

        case frozenset(), frozenset():
            old_total = len(old)
            new_total = len(new)
            total = old_total + new_total

            if total == 0:
                return 1.0
            elif ratio(old_total, new_total) < SIMILARITY_MIN_RATIO:
                return 0.0
            else:
                return len(old & new) * 2 / total

        case str(), str():
            return get_line_similarity(old, new)

        case _:
            return 0.0


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


def get_line_counts(lines: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()

    for line in lines:
        line = line.strip()
        if line:
            counts[line] += 1

    return counts


WINDOW_SIZE = 48
WINDOW_MASK = (1 << 12) - 1

HASH_BASE = 263
HASH_MODULUS = (1 << 31) - 1
HASH_BASE_POWER = pow(HASH_BASE, WINDOW_SIZE, HASH_MODULUS)


def get_binary_chunks(path: Path) -> Iterator[bytes]:
    with (
        path.open("rb") as file,
        mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as raw_data,
        memoryview(raw_data) as data,
    ):
        if len(data) <= WINDOW_SIZE:
            yield stable_hash(data)
            return

        curr_hash = 0
        for i in range(WINDOW_SIZE):
            curr_hash = (curr_hash * HASH_BASE + data[i]) % HASH_MODULUS

        start = 0
        for i in range(WINDOW_SIZE, len(data)):
            if curr_hash & WINDOW_MASK == 0:
                yield stable_hash(data[start:i])
                start = i

            old_byte = data[i - WINDOW_SIZE]
            new_byte = data[i]

            curr_hash = (
                curr_hash - (old_byte * HASH_BASE_POWER) % HASH_MODULUS
            ) % HASH_MODULUS
            curr_hash = (curr_hash * HASH_BASE + new_byte) % HASH_MODULUS

        yield stable_hash(data[start:])


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
    elif not old or not new:
        return 0
    else:
        return SequenceMatcher(None, old, new).ratio()


def diff_lines(old: Sequence[str], new: Sequence[str]) -> list[Line]:
    old_stripped = [line.lstrip() for line in old]
    new_stripped = [line.lstrip() for line in new]

    lines: list[Line] = []
    old_start = 0
    new_start = 0

    keep_sections = iter(_myers_keep_sections(old_stripped, new_stripped))

    while True:
        section = next(keep_sections, None)

        if section is None:
            old_end = len(old)
            new_end = len(new)
        else:
            old_end = section.old_start
            new_end = section.new_start

        if old_start < old_end and new_start < new_end:
            for op in _similarity_diff(
                old, new, old_start, old_end, new_start, new_end
            ):
                if op == "add":
                    old_line = None
                else:
                    old_line = old[old_start]
                    old_start += 1

                if op == "delete":
                    new_line = None
                else:
                    new_line = new[new_start]
                    new_start += 1

                lines.append(Line(old_line, new_line))

        elif old_start < old_end:
            lines.extend(
                Line(old[old_index], None) for old_index in range(old_start, old_end)
            )
        elif new_start < new_end:
            lines.extend(
                Line(None, new[new_index]) for new_index in range(new_start, new_end)
            )

        if section is None:
            break

        lines.extend(
            Line(old[old_index], new[new_index])
            for old_index, new_index in zip(
                range(section.old_start, section.old_end),
                range(section.new_start, section.new_end),
            )
        )

        old_start = section.old_end
        new_start = section.new_end

    return lines


@dataclass(frozen=True)
class Section:
    old_start: int
    old_end: int
    new_start: int
    new_end: int


def _myers_keep_sections(old: list[str], new: list[str]) -> list[Section]:
    old_len = len(old)
    new_len = len(new)
    reaches: list[dict[int, int]] = []

    while True:
        edits = len(reaches)

        if edits <= old_len:
            min_diagonal = -edits
        elif edits % 2 == old_len % 2:
            min_diagonal = -old_len
        else:
            min_diagonal = -old_len + 1

        reach: dict[int, int] = {}
        prev_reach = reaches[-1] if reaches else {}

        for diagonal in range(min_diagonal, min(edits, new_len) + 1, 2):
            new_index = max(
                prev_reach.get(diagonal - 1, -1) + 1,
                prev_reach.get(diagonal + 1, 0),
            )
            old_index = new_index - diagonal

            while (
                old_index < old_len
                and new_index < new_len
                and old[old_index] == new[new_index]
            ):
                old_index += 1
                new_index += 1

            reach[diagonal] = new_index

        reaches.append(reach)
        if reach.get(new_len - old_len) == new_len:
            break

    sections: list[Section] = []
    diagonal = new_len - old_len

    for edits in reversed(range(1, len(reaches))):
        prev_reach = reaches[edits - 1]
        entry_index_add = prev_reach.get(diagonal - 1, -2) + 1
        entry_index_delete = prev_reach.get(diagonal + 1, -1)
        entry_index = max(entry_index_add, entry_index_delete)

        new_index = reaches[edits][diagonal]
        if entry_index < new_index:
            section = Section(
                entry_index - diagonal,
                new_index - diagonal,
                entry_index,
                new_index,
            )
            sections.append(section)

        if entry_index == entry_index_add:
            diagonal = diagonal - 1
        else:
            diagonal = diagonal + 1

    new_index = reaches[0][0]
    if new_index > 0:
        sections.append(Section(0, new_index, 0, new_index))

    sections.reverse()
    return sections


type Op = Literal["add", "change", "delete"]
type Pos = tuple[int, int]


# This is kind of the reverse priority of how you want this to be ordered, this
# key makes this operation have priority when it is the incoming operation for
# a node. And thus actually prioritizes it to be the last operation to a node
# where there would be multiple equivalent paths and thus show up later in the
# ordering.
OP_KEY: dict[Op, int] = {"add": 0, "delete": 1, "change": 2}


@dataclass(frozen=True)
class State:
    source: tuple[Pos, Op] | None
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    cost: float

    @property
    def heuristic(self) -> int:
        old_todo = self.old_end - self.old_start
        new_todo = self.new_end - self.new_start
        return abs(old_todo - new_todo)

    def _key(self) -> tuple[float, int]:
        assert self.source is not None
        return (self.cost + self.heuristic, OP_KEY[self.source[1]])

    def __lt__(self, other: "State", /) -> bool:
        return self._key() < other._key()

    @property
    def pos(self) -> Pos:
        return (self.old_start, self.new_start)

    def derive(
        self, op: Op, old_delta: int, new_delta: int, cost_delta: float
    ) -> "State":
        return State(
            (self.pos, op),
            self.old_start + old_delta,
            self.old_end,
            self.new_start + new_delta,
            self.new_end,
            self.cost + cost_delta,
        )


def _similarity_diff(
    old: Sequence[str],
    new: Sequence[str],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> list[Op]:
    states = [State(None, old_start, old_end, new_start, new_end, 0)]
    sources: dict[Pos, tuple[Pos, Op] | None] = {}

    while True:
        state = heapq.heappop(states)

        if state.pos in sources:
            continue
        sources[state.pos] = state.source

        old_todo = old_end - state.old_start
        new_todo = new_end - state.new_start

        if not old_todo and not new_todo:
            break

        if old_todo:
            heapq.heappush(states, state.derive("delete", 1, 0, 1))

        if new_todo:
            heapq.heappush(states, state.derive("add", 0, 1, 1))

        if old_todo and new_todo:
            old_line = old[state.old_start]
            new_line = new[state.new_start]
            similarity = get_line_similarity(old_line, new_line)

            if similarity >= SIMILARITY_THRESHOLD:
                heapq.heappush(
                    states, state.derive("change", 1, 1, 2 * (1 - similarity))
                )

    ops: list[Op] = []
    pos = (old_end, new_end)

    while source := sources[pos]:
        pos, line = source
        ops.append(line)

    ops.reverse()
    return ops
