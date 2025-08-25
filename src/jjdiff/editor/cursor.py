from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from typing import cast, override

from ..change import (
    FILE_CHANGE_TYPES,
    Change,
    ChangeRef,
    FileChange,
    LineRef,
    Ref,
    get_change_refs,
)


class Cursor(ABC):
    @abstractmethod
    def is_change_selected(self, change: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_title_selected(self, change: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_line_selected(self, change: int, line: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_all_lines_selected(self, change: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def next(self, changes: Sequence[Change], opened: set[ChangeRef]) -> "Cursor":
        raise NotImplementedError

    @abstractmethod
    def prev(self, changes: Sequence[Change], opened: set[ChangeRef]) -> "Cursor":
        raise NotImplementedError

    @abstractmethod
    def grow(
        self, changes: Sequence[Change], opened: set[ChangeRef]
    ) -> "Cursor | ChangeRef":
        raise NotImplementedError

    @abstractmethod
    def shrink(
        self, changes: Sequence[Change], opened: set[ChangeRef]
    ) -> "Cursor | ChangeRef":
        raise NotImplementedError

    @abstractmethod
    def refs(self, changes: Sequence[Change]) -> Iterator[Ref]:
        raise NotImplementedError


class ChangeCursor(Cursor):
    change: int

    def __init__(self, change: int):
        self.change = change

    @override
    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    @override
    def is_title_selected(self, change: int) -> bool:
        return self.change == change

    @override
    def is_line_selected(self, change: int, line: int) -> bool:
        return self.change == change

    @override
    def is_all_lines_selected(self, change: int) -> bool:
        return self.change == change

    @override
    def next(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        return ChangeCursor((self.change + 1) % len(changes))

    @override
    def prev(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        return ChangeCursor((self.change - 1) % len(changes))

    @override
    def grow(
        self, changes: Sequence[Change], opened: set[ChangeRef]
    ) -> Cursor | ChangeRef:
        # Check if we need to close the change, other than that we cannot
        # grow further
        change_ref = ChangeRef(self.change)
        if change_ref in opened:
            return change_ref
        else:
            return self

    @override
    def shrink(
        self, changes: Sequence[Change], opened: set[ChangeRef]
    ) -> Cursor | ChangeRef:
        # First check if we still need to open it
        change_ref = ChangeRef(self.change)
        if change_ref not in opened:
            return change_ref

        # If it is not a file change we cannot shrink more
        change = changes[self.change]
        if not isinstance(change, FILE_CHANGE_TYPES):
            return self

        # Now we find the first hunk
        start = 0
        while change.lines[start].status == "unchanged":
            start += 1

        end = start + 1
        while end < len(change.lines) and change.lines[end].status != "unchanged":
            end += 1

        return HunkCursor(self.change, start, end)

    @override
    def refs(self, changes: Sequence[Change]) -> Iterator[Ref]:
        return get_change_refs(self.change, changes[self.change])


class HunkCursor(Cursor):
    change: int
    start: int
    end: int

    def __init__(self, change: int, start: int, end: int):
        self.change = change
        self.start = start
        self.end = end

    @override
    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    @override
    def is_title_selected(self, change: int) -> bool:
        return False

    @override
    def is_line_selected(self, change: int, line: int) -> bool:
        return self.change == change and self.start <= line < self.end

    @override
    def is_all_lines_selected(self, change: int) -> bool:
        return False

    @override
    def prev(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        change_index = self.change
        start = self.start
        end = self.end

        while True:
            change = cast(FileChange, changes[change_index])

            # Try to find the previous hunk end
            end = start
            while end > 0:
                if change.lines[end - 1].status != "unchanged":
                    break
                end -= 1
            else:
                # No hunk found, so go to the previous file change and try
                # again
                while True:
                    change_index = (change_index - 1) % len(changes)
                    if ChangeRef(change_index) not in opened:
                        continue

                    prev_change = changes[change_index]
                    if isinstance(prev_change, FILE_CHANGE_TYPES):
                        break

                start = len(prev_change.lines)
                continue

            # Find the start of the hunk
            start = end - 1
            while start > 0 and change.lines[start - 1].status != "unchanged":
                start -= 1

            return HunkCursor(change_index, start, end)

    @override
    def next(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        change_index = self.change
        start = self.start
        end = self.end

        while True:
            change = cast(FileChange, changes[change_index])

            # Try to find the next hunk start
            start = end
            while start < len(change.lines):
                if change.lines[start].status != "unchanged":
                    break
                start += 1
            else:
                # No hunk found, so go to the next file change and try again
                while True:
                    change_index = (change_index + 1) % len(changes)
                    if ChangeRef(change_index) not in opened:
                        continue

                    next_change = changes[change_index]
                    if isinstance(next_change, FILE_CHANGE_TYPES):
                        break

                end = 0
                continue

            # Find the start of the hunk
            end = start + 1
            while end < len(change.lines) and change.lines[end].status != "unchanged":
                end += 1

            return HunkCursor(change_index, start, end)

    @override
    def grow(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        return ChangeCursor(self.change)

    @override
    def shrink(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        return LineCursor(self.change, self.start)

    @override
    def refs(self, changes: Sequence[Change]) -> Iterator[Ref]:
        for line in range(self.start, self.end):
            yield LineRef(self.change, line)


class LineCursor(Cursor):
    change: int
    line: int

    def __init__(self, change: int, line: int):
        self.change = change
        self.line = line

    @override
    def is_change_selected(self, change: int) -> bool:
        return self.change == change

    @override
    def is_title_selected(self, change: int) -> bool:
        return False

    @override
    def is_line_selected(self, change: int, line: int) -> bool:
        return self.change == change and self.line == line

    @override
    def is_all_lines_selected(self, change: int) -> bool:
        return False

    @override
    def prev(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        change_index = self.change
        line = self.line

        while True:
            change = cast(FileChange, changes[change_index])

            # Try to find the previous line
            while line > 0:
                line -= 1
                if change.lines[line].status != "unchanged":
                    break
            else:
                # No line found, so go to the previous file change and try
                # again
                while True:
                    change_index = (change_index - 1) % len(changes)
                    if ChangeRef(change_index) not in opened:
                        continue

                    prev_change = changes[change_index]
                    if isinstance(prev_change, FILE_CHANGE_TYPES):
                        break

                line = len(prev_change.lines)
                continue

            return LineCursor(change_index, line)

    @override
    def next(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        change_index = self.change
        line = self.line

        while True:
            change = cast(FileChange, changes[change_index])

            # Try to find the next line
            while line + 1 < len(change.lines):
                line += 1
                if change.lines[line].status != "unchanged":
                    break
            else:
                # No line found, so go to the previous file change and try
                # again
                while True:
                    change_index = (change_index + 1) % len(changes)
                    if ChangeRef(change_index) not in opened:
                        continue

                    next_change = changes[change_index]
                    if isinstance(next_change, FILE_CHANGE_TYPES):
                        break

                line = -1
                continue

            return LineCursor(change_index, line)

    @override
    def grow(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        # Expand current line into the hunk it is in
        change = cast(FileChange, changes[self.change])

        start = self.line
        while start > 0 and change.lines[start - 1].status != "unchanged":
            start -= 1

        end = self.line + 1
        while end < len(change.lines) and change.lines[end].status != "unchanged":
            end += 1

        return HunkCursor(self.change, start, end)

    @override
    def shrink(self, changes: Sequence[Change], opened: set[ChangeRef]) -> Cursor:
        # Cannot shrink further
        return self

    @override
    def refs(self, changes: Sequence[Change]) -> Iterator[Ref]:
        yield LineRef(self.change, self.line)
