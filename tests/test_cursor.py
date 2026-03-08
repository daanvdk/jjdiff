from pathlib import Path

from jjdiff.change import ChangeRef, Line, LineRef, ModifyFile
from jjdiff.editor.cursor import ChangeCursor, HunkCursor, LineCursor


def one_change() -> list[ModifyFile]:
    return [ModifyFile(Path("a.py"), [Line("old", "new")])]


def two_changes() -> list[ModifyFile]:
    return [
        ModifyFile(Path("a.py"), [Line("a1", "b1")]),
        ModifyFile(Path("b.py"), [Line("a2", "b2")]),
    ]


# --- ChangeCursor ---


def test_change_cursor_next() -> None:
    cursor = ChangeCursor(0)
    result = cursor.next(two_changes(), set())
    assert isinstance(result, ChangeCursor)
    assert result.change == 1


def test_change_cursor_next_wraps() -> None:
    cursor = ChangeCursor(0)
    result = cursor.next(one_change(), set())
    assert isinstance(result, ChangeCursor)
    assert result.change == 0


def test_change_cursor_prev_wraps() -> None:
    cursor = ChangeCursor(0)
    result = cursor.prev(two_changes(), set())
    assert isinstance(result, ChangeCursor)
    assert result.change == 1


def test_change_cursor_first() -> None:
    cursor = ChangeCursor(1)
    result = cursor.first(two_changes(), set())
    assert isinstance(result, ChangeCursor)
    assert result.change == 0


def test_change_cursor_last() -> None:
    cursor = ChangeCursor(0)
    result = cursor.last(two_changes(), set())
    assert isinstance(result, ChangeCursor)
    assert result.change == 1


def test_change_cursor_refs() -> None:
    cursor = ChangeCursor(0)
    refs = list(cursor.refs(one_change()))
    assert LineRef(0, 0) in refs


def test_change_cursor_grow_returns_change_ref_when_opened() -> None:
    cursor = ChangeCursor(0)
    result = cursor.grow(one_change(), {ChangeRef(0)})
    assert result == ChangeRef(0)


def test_change_cursor_grow_returns_self_when_closed() -> None:
    cursor = ChangeCursor(0)
    result = cursor.grow(one_change(), set())
    assert result is cursor


def test_change_cursor_shrink_returns_change_ref_when_closed() -> None:
    cursor = ChangeCursor(0)
    result = cursor.shrink(one_change(), set())
    assert result == ChangeRef(0)


def test_change_cursor_shrink_returns_hunk_cursor_when_opened() -> None:
    cursor = ChangeCursor(0)
    result = cursor.shrink(one_change(), {ChangeRef(0)})
    assert isinstance(result, HunkCursor)
    assert result.change == 0
    assert result.start == 0


# --- HunkCursor ---


def test_hunk_cursor_next_same_change() -> None:
    changes = [
        ModifyFile(
            Path("a.py"),
            [
                Line("a", "b"),  # line 0: changed (hunk 1)
                Line("x", "x"),  # line 1: unchanged
                Line("c", "d"),  # line 2: changed (hunk 2)
            ],
        )
    ]
    opened = {ChangeRef(0)}
    cursor = HunkCursor(0, 0, 1)
    result = cursor.next(changes, opened)
    assert isinstance(result, HunkCursor)
    assert result.change == 0
    assert result.start == 2


def test_hunk_cursor_next_crosses_change() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("a", "b")]),
        ModifyFile(Path("b.py"), [Line("c", "d")]),
    ]
    opened = {ChangeRef(0), ChangeRef(1)}
    cursor = HunkCursor(0, 0, 1)
    result = cursor.next(changes, opened)
    assert isinstance(result, HunkCursor)
    assert result.change == 1


def test_hunk_cursor_prev_same_change() -> None:
    changes = [
        ModifyFile(
            Path("a.py"),
            [
                Line("a", "b"),  # line 0: changed (hunk 1)
                Line("x", "x"),  # line 1: unchanged
                Line("c", "d"),  # line 2: changed (hunk 2)
            ],
        )
    ]
    opened = {ChangeRef(0)}
    cursor = HunkCursor(0, 2, 3)
    result = cursor.prev(changes, opened)
    assert isinstance(result, HunkCursor)
    assert result.change == 0
    assert result.start == 0


def test_hunk_cursor_refs() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("a", "b"), Line("c", "d"), Line("e", "f")])
    ]
    cursor = HunkCursor(0, 0, 3)
    refs = list(cursor.refs(changes))
    assert refs == [LineRef(0, 0), LineRef(0, 1), LineRef(0, 2)]


def test_hunk_cursor_grow_returns_change_cursor() -> None:
    cursor = HunkCursor(0, 0, 1)
    result = cursor.grow(one_change(), {ChangeRef(0)})
    assert isinstance(result, ChangeCursor)
    assert result.change == 0


def test_hunk_cursor_shrink_returns_line_cursor() -> None:
    cursor = HunkCursor(0, 0, 2)
    result = cursor.shrink(one_change(), {ChangeRef(0)})
    assert isinstance(result, LineCursor)
    assert result.change == 0
    assert result.line == 0


# --- LineCursor ---


def test_line_cursor_refs() -> None:
    cursor = LineCursor(0, 0)
    refs = list(cursor.refs(one_change()))
    assert refs == [LineRef(0, 0)]


def test_line_cursor_grow_to_hunk() -> None:
    changes = [ModifyFile(Path("a.py"), [Line("a", "b"), Line("c", "d")])]
    cursor = LineCursor(0, 0)
    result = cursor.grow(changes, set())
    assert isinstance(result, HunkCursor)
    assert result.start == 0
    assert result.end == 2


def test_line_cursor_shrink_returns_self() -> None:
    cursor = LineCursor(0, 0)
    result = cursor.shrink(one_change(), set())
    assert result is cursor


def test_line_cursor_next_same_change() -> None:
    changes = [
        ModifyFile(
            Path("a.py"),
            [
                Line("a", "b"),  # line 0: changed
                Line("x", "x"),  # line 1: unchanged
                Line("c", "d"),  # line 2: changed
            ],
        )
    ]
    opened = {ChangeRef(0)}
    cursor = LineCursor(0, 0)
    result = cursor.next(changes, opened)
    assert isinstance(result, LineCursor)
    assert result.change == 0
    assert result.line == 2


def test_line_cursor_prev_same_change() -> None:
    changes = [
        ModifyFile(
            Path("a.py"),
            [
                Line("a", "b"),  # line 0: changed
                Line("x", "x"),  # line 1: unchanged
                Line("c", "d"),  # line 2: changed
            ],
        )
    ]
    opened = {ChangeRef(0)}
    cursor = LineCursor(0, 2)
    result = cursor.prev(changes, opened)
    assert isinstance(result, LineCursor)
    assert result.change == 0
    assert result.line == 0


# --- HunkCursor.first / last ---


def test_hunk_cursor_first() -> None:
    cursor = HunkCursor(1, 0, 1)
    result = cursor.first(two_changes(), set())
    assert isinstance(result, HunkCursor)
    assert result.change == 0
    assert result.start == 0


def test_hunk_cursor_last() -> None:
    cursor = HunkCursor(0, 0, 1)
    result = cursor.last(two_changes(), set())
    assert isinstance(result, HunkCursor)
    assert result.change == 1


# --- LineCursor.first / last ---


def test_line_cursor_first() -> None:
    cursor = LineCursor(1, 0)
    result = cursor.first(two_changes(), set())
    assert isinstance(result, LineCursor)
    assert result.change == 0
    assert result.line == 0


def test_line_cursor_last() -> None:
    cursor = LineCursor(0, 0)
    result = cursor.last(two_changes(), set())
    assert isinstance(result, LineCursor)
    assert result.change == 1
    assert result.line == 0


# --- Cross-change navigation ---


def test_hunk_cursor_prev_crosses_change() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("a1", "b1")]),
        ModifyFile(Path("b.py"), [Line("a2", "b2")]),
    ]
    opened = {ChangeRef(0), ChangeRef(1)}
    # Cursor is at start of change 1 (start=0, end=1); prev should cross to change 0
    cursor = HunkCursor(1, 0, 1)
    result = cursor.prev(changes, opened)
    assert isinstance(result, HunkCursor)
    assert result.change == 0


def test_line_cursor_next_crosses_change() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("a1", "b1")]),
        ModifyFile(Path("b.py"), [Line("a2", "b2")]),
    ]
    opened = {ChangeRef(0), ChangeRef(1)}
    # Cursor is at the only changed line of change 0; next crosses to change 1
    cursor = LineCursor(0, 0)
    result = cursor.next(changes, opened)
    assert isinstance(result, LineCursor)
    assert result.change == 1
    assert result.line == 0


def test_line_cursor_prev_crosses_change() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("a1", "b1")]),
        ModifyFile(Path("b.py"), [Line("a2", "b2")]),
    ]
    opened = {ChangeRef(0), ChangeRef(1)}
    # Cursor is at first changed line of change 1; prev crosses to change 0
    cursor = LineCursor(1, 0)
    result = cursor.prev(changes, opened)
    assert isinstance(result, LineCursor)
    assert result.change == 0
    assert result.line == 0
