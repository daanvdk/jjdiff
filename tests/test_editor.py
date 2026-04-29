from pathlib import Path

from jjdiff.change import (
    AddFile,
    ChangeRef,
    Line,
    LineRef,
    ModifyFile,
)
from jjdiff.config import Config
from jjdiff.editor.cursor import ChangeCursor, HunkCursor
from jjdiff.editor.editor import Editor


def two_changes() -> list[ModifyFile]:
    return [
        ModifyFile(Path("a.py"), [Line("old_a", "new_a")]),
        ModifyFile(Path("b.py"), [Line("old_b", "new_b")]),
    ]


# --- Cursor navigation ---


def test_cursor_next() -> None:
    editor = Editor(two_changes())
    assert editor.cursor.change == 0
    editor.next_cursor()
    assert editor.cursor.change == 1


def test_cursor_prev() -> None:
    editor = Editor(two_changes())
    editor.next_cursor()
    editor.prev_cursor()
    assert editor.cursor.change == 0


def test_cursor_next_wraps() -> None:
    changes = [ModifyFile(Path("a.py"), [Line("old", "new")])]
    editor = Editor(changes)
    editor.next_cursor()
    assert editor.cursor.change == 0


def test_cursor_prev_wraps() -> None:
    editor = Editor(two_changes())
    editor.prev_cursor()
    assert editor.cursor.change == 1


def test_first_cursor() -> None:
    editor = Editor(two_changes())
    editor.next_cursor()
    editor.first_cursor()
    assert editor.cursor.change == 0


def test_last_cursor() -> None:
    editor = Editor(two_changes())
    editor.last_cursor()
    assert editor.cursor.change == 1


# --- Open / close ---


def test_shrink_cursor_opens_change() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    assert ChangeRef(0) not in editor.opened
    editor.shrink_cursor()
    assert ChangeRef(0) in editor.opened


def test_shrink_cursor_twice_moves_to_hunk() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.shrink_cursor()  # opens change
    editor.shrink_cursor()  # moves cursor into hunk
    assert isinstance(editor.cursor, HunkCursor)


def test_grow_cursor_closes_change() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.shrink_cursor()  # opens change
    editor.shrink_cursor()  # cursor becomes HunkCursor
    editor.grow_cursor()  # HunkCursor → ChangeCursor
    assert isinstance(editor.cursor, ChangeCursor)
    assert ChangeRef(0) in editor.opened  # still open
    editor.grow_cursor()  # ChangeCursor on open change → closes
    assert ChangeRef(0) not in editor.opened


def test_open_all() -> None:
    editor = Editor(two_changes())
    editor.open_all()
    assert ChangeRef(0) in editor.opened
    assert ChangeRef(1) in editor.opened


def test_close_all() -> None:
    editor = Editor(two_changes())
    editor.open_all()
    editor.close_all()
    assert len(editor.opened) == 0
    assert isinstance(editor.cursor, ChangeCursor)


# --- Auto-open behavior ---


def test_auto_open_on_move(config: Config) -> None:
    config.editor.auto_open = True
    editor = Editor(two_changes())
    editor.opened.add(ChangeRef(0))
    editor.next_cursor()
    assert ChangeRef(0) not in editor.opened
    assert ChangeRef(1) in editor.opened


def test_no_auto_open_on_move(config: Config) -> None:
    config.editor.auto_open = False
    editor = Editor(two_changes())
    editor.opened.add(ChangeRef(0))
    editor.next_cursor()
    assert ChangeRef(0) in editor.opened  # unchanged
    assert ChangeRef(1) not in editor.opened


# --- Default-open behavior ---


def test_default_open(config: Config) -> None:
    config.editor.default_open = True
    editor = Editor(two_changes())
    assert ChangeRef(0) in editor.opened
    assert ChangeRef(1) in editor.opened


# --- Selection ---


def test_select_cursor() -> None:
    editor = Editor(two_changes())
    editor.select_cursor()
    assert LineRef(0, 0) in editor.included
    assert editor.cursor.change == 1


def test_invert_selection() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    assert LineRef(0, 0) in editor.included


def test_invert_selection_toggle() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    assert LineRef(0, 0) in editor.included
    editor.invert_selection()
    assert LineRef(0, 0) not in editor.included


def test_invert_selection_mixed_state() -> None:
    editor = Editor(two_changes())
    editor.select_refs([LineRef(0, 0)])
    editor.invert_selection()
    assert LineRef(0, 0) not in editor.included
    assert LineRef(1, 0) in editor.included


def test_invert_selection_shrinks_unmet_deps() -> None:
    changes = [AddFile(Path("a.py"), [Line(None, "hello")], False)]
    editor = Editor(changes)
    editor.select_refs([LineRef(0, 0)])  # select only the line, not the file
    editor.invert_selection()
    # ChangeRef(0) would need LineRef(0, 0) but that gets deselected, so it's dropped
    assert ChangeRef(0) not in editor.included
    assert LineRef(0, 0) not in editor.included


def test_invert_selection_no_op_does_not_push_undo() -> None:
    editor = Editor([])
    editor.invert_selection()
    assert len(editor.undo_stack) == 0


def test_select_includes_dependencies() -> None:
    # AddFile: selecting ChangeRef auto-includes its lines (they are its "dependencies")
    changes = [AddFile(Path("a.py"), [Line(None, "hello")], False)]
    editor = Editor(changes)
    editor.select_refs([ChangeRef(0)])
    assert ChangeRef(0) in editor.included
    assert LineRef(0, 0) in editor.included


def test_deselect_includes_dependants() -> None:
    # AddFile: deselecting a LineRef auto-removes the ChangeRef (which depends on lines)
    changes = [AddFile(Path("a.py"), [Line(None, "hello")], False)]
    editor = Editor(changes)
    editor.invert_selection()
    assert ChangeRef(0) in editor.included
    assert LineRef(0, 0) in editor.included
    editor.select_refs([LineRef(0, 0)])  # deselect the line
    assert LineRef(0, 0) not in editor.included
    assert ChangeRef(0) not in editor.included  # dependant auto-removed


# --- Undo / redo ---


def test_undo_invert_selection() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    assert LineRef(0, 0) in editor.included
    editor.undo()
    assert LineRef(0, 0) not in editor.included


def test_redo_invert_selection() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    editor.undo()
    editor.redo()
    assert LineRef(0, 0) in editor.included


def test_undo_restores_cursor_and_opened() -> None:
    editor = Editor(two_changes())
    editor.next_cursor()
    assert editor.cursor.change == 1
    editor.select_cursor()  # saves cursor=1, then moves to 0
    assert editor.cursor.change == 0
    assert LineRef(1, 0) in editor.included
    editor.undo()
    assert editor.cursor.change == 1
    assert LineRef(1, 0) not in editor.included


def test_undo_empty_does_nothing() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.undo()
    assert editor.cursor.change == 0


def test_redo_empty_does_nothing() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.redo()
    assert editor.cursor.change == 0


def test_invert_selection_clears_redo() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    editor.undo()
    assert len(editor.redo_stack) == 1
    editor.invert_selection()
    assert len(editor.redo_stack) == 0


# --- Confirm / exit ---


def test_confirm() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.invert_selection()
    editor.confirm()
    assert isinstance(editor._result, frozenset)
    assert LineRef(0, 0) in editor._result


def test_exit() -> None:
    editor = Editor([ModifyFile(Path("a.py"), [Line("old", "new")])])
    editor.exit()
    assert editor._result is None


def test_empty_changes_sets_result() -> None:
    editor = Editor([])
    assert editor._result == frozenset()
