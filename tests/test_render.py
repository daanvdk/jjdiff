import re
from pathlib import Path

from jjdiff.change import (
    AddBinary,
    AddFile,
    AddSymlink,
    ChangeMode,
    ChangeRef,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    Line,
    LineRef,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Ref,
    Rename,
)
from jjdiff.config import Config
from jjdiff.editor.cursor import ChangeCursor
from jjdiff.editor.render.change import render_change
from jjdiff.editor.render.change_file import render_change_file
from jjdiff.editor.render.change_title import render_change_title
from jjdiff.editor.render.changes import render_changes
from jjdiff.tui.drawable import Drawable

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def render_plain(drawable: Drawable, width: int = 80) -> list[str]:
    lines = list(drawable.render(width, None))
    return [ANSI_ESCAPE.sub("", line) for line in lines]


# --- change_title rendering ---


def test_render_title_add_file() -> None:
    change = AddFile(Path("foo.py"), [Line(None, "x")], False)
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert "add" in lines[0]
    assert "foo.py" in lines[0]


def test_render_title_modify_file() -> None:
    change = ModifyFile(Path("bar.py"), [Line("old", "new")])
    drawable = render_change_title(change, selected=False, included="none", renames={})
    lines = render_plain(drawable)
    assert "modify" in lines[0]
    assert "bar.py" in lines[0]


def test_render_title_included_full() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    drawable = render_change_title(change, selected=False, included="full", renames={})
    lines = render_plain(drawable)
    assert "\u2713" in lines[0]  # checkmark


def test_render_title_included_partial() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    drawable = render_change_title(
        change, selected=False, included="partial", renames={}
    )
    lines = render_plain(drawable)
    assert "\u2212" in lines[0]  # minus sign


def test_render_title_not_included() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    drawable = render_change_title(change, selected=False, included="none", renames={})
    lines = render_plain(drawable)
    assert "\u2717" in lines[0]  # cross


def test_render_title_selected_adds_marker() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    drawable = render_change_title(change, selected=True, included=None, renames={})
    # selected=True wraps in Rows([SelectionMarker(), title]) → 1 visible line
    lines = render_plain(drawable)
    assert len(lines) == 1
    assert "modify" in lines[0]


# --- render_change dispatch ---


def test_render_change_closed_shows_only_title() -> None:
    change = ModifyFile(Path("a.py"), [Line("old_unique", "new_unique")])
    drawable = render_change(0, change, ChangeCursor(0), None, opened=False, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    assert not any("old_unique" in line for line in lines)


def test_render_change_modify_file_opened_shows_content() -> None:
    change = ModifyFile(Path("a.py"), [Line("old_content", "new_content")])
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    assert any("old_content" in line for line in lines)
    assert any("new_content" in line for line in lines)


def test_render_change_add_file_opened() -> None:
    change = AddFile(Path("new.py"), [Line(None, "content_xyz")], False)
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("add" in line for line in lines)
    assert any("content_xyz" in line for line in lines)


def test_render_change_binary_shows_textbox() -> None:
    change = AddBinary(Path("image.png"), Path("/dev/null"), False)
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("add" in line for line in lines)
    assert any("cannot display binary file" in line for line in lines)


def test_render_change_deprioritized_in_print_mode(config: Config) -> None:
    # cursor=None (print mode) + deprioritized path → renders textbox
    config.diff.deprioritize = ["*.lock"]
    change = ModifyFile(Path("package.lock"), [Line("old", "new")])
    drawable = render_change(0, change, None, None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    assert any("hidden changes to deprioritized file" in line for line in lines)


def test_render_change_deprioritized_in_editor_mode(config: Config) -> None:
    # cursor!=None (editor mode) + deprioritized path → renders normally
    config.diff.deprioritize = ["*.lock"]
    change = ModifyFile(Path("package.lock"), [Line("old_lock", "new_lock")])
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("old_lock" in line for line in lines)
    assert not any("hidden" in line for line in lines)


def test_render_change_included_computes_full() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    included: set[Ref] = {LineRef(0, 0)}
    drawable = render_change(
        0, change, ChangeCursor(0), included, opened=True, renames={}
    )
    lines = render_plain(drawable)
    # title shows checkmark (full inclusion)
    assert any("\u2713" in line for line in lines)


def test_render_change_included_computes_none() -> None:
    change = ModifyFile(Path("a.py"), [Line("old", "new")])
    included: set[Ref] = set()
    drawable = render_change(
        0, change, ChangeCursor(0), included, opened=True, renames={}
    )
    lines = render_plain(drawable)
    # title shows cross (not included)
    assert any("\u2717" in line for line in lines)


# --- change_file rendering details ---


def test_render_file_add_only() -> None:
    lines = [Line(None, "hello"), Line(None, "world")]
    drawable = render_change_file(0, lines, None)
    result = render_plain(drawable)
    assert any("hello" in line for line in result)
    assert any("world" in line for line in result)
    assert not any("omitted" in line for line in result)


def test_render_file_context_collapse() -> None:
    # Changed line, 10 unchanged, changed line → should collapse context
    file_lines = [Line("a", "b")] + [Line("x", "x")] * 10 + [Line("c", "d")]
    drawable = render_change_file(0, file_lines, None)
    result = render_plain(drawable)
    assert any("omitted" in line for line in result)


def test_render_file_no_collapse_with_few_unchanged() -> None:
    # Only 1 unchanged line between hunks → no collapse
    file_lines = [Line("a", "b"), Line("x", "x"), Line("c", "d")]
    drawable = render_change_file(0, file_lines, None)
    result = render_plain(drawable)
    assert not any("omitted" in line for line in result)


def test_render_file_included_line_shows_checkmark() -> None:
    file_lines = [Line("old", "new")]
    included: set[Ref] = {LineRef(0, 0)}
    drawable = render_change_file(0, file_lines, None, included)
    result = render_plain(drawable)
    assert any("\u2713" in line for line in result)


def test_render_file_excluded_line_shows_cross() -> None:
    file_lines = [Line("old", "new")]
    included: set[Ref] = set()  # LineRef(0, 0) not in included → False
    drawable = render_change_file(0, file_lines, None, included)
    result = render_plain(drawable)
    assert any("\u2717" in line for line in result)


# --- Full changes rendering ---


def test_render_changes_closed() -> None:
    changes = [ModifyFile(Path("a.py"), [Line("old_unique", "new_unique")])]
    cursor = ChangeCursor(0)
    # opened=set() → change is closed
    drawable = render_changes(changes, cursor, None, set())
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    assert not any("old_unique" in line for line in lines)


def test_render_changes_opened() -> None:
    changes = [ModifyFile(Path("a.py"), [Line("old_content", "new_content")])]
    cursor = ChangeCursor(0)
    drawable = render_changes(changes, cursor, None, {ChangeRef(0)})
    lines = render_plain(drawable)
    assert any("old_content" in line for line in lines)
    assert any("new_content" in line for line in lines)


def test_render_changes_none_cursor() -> None:
    # cursor=None is print mode, opened=None means all open
    changes = [ModifyFile(Path("a.py"), [Line("old", "new")])]
    drawable = render_changes(changes, None, None, None)
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)


def test_render_changes_multiple() -> None:
    changes = [
        ModifyFile(Path("a.py"), [Line("x", "y")]),
        ModifyFile(Path("b.py"), [Line("p", "q")]),
    ]
    cursor = ChangeCursor(0)
    drawable = render_changes(changes, cursor, None, set())
    lines = render_plain(drawable)
    assert any("a.py" in line for line in lines)
    assert any("b.py" in line for line in lines)


# --- change_title: additional change types ---


def test_render_title_rename() -> None:
    change = Rename(Path("old.py"), Path("new.py"))
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("rename" in line for line in lines)
    assert any("old.py" in line for line in lines)
    assert any("to" in line for line in lines)
    assert any("new.py" in line for line in lines)


def test_render_title_change_mode() -> None:
    change = ChangeMode(Path("script.sh"), False, True)
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("change mode" in line for line in lines)


def test_render_title_add_symlink() -> None:
    change = AddSymlink(Path("link"), Path("/target"))
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("add" in line for line in lines)
    assert any("symlink" in line for line in lines)


def test_render_title_modify_binary() -> None:
    change = ModifyBinary(Path("img.png"), Path("/tmp/old"), Path("/tmp/new"))
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)


def test_render_title_modify_symlink() -> None:
    change = ModifySymlink(Path("link"), Path("/old"), Path("/new"))
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    assert any("symlink" in line for line in lines)


def test_render_title_delete_file_shows_deleted_count() -> None:
    change = DeleteFile(Path("gone.py"), [Line("x", None)], False)
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("delete" in line for line in lines)
    assert any("-1" in line for line in lines)


def test_render_title_delete_binary() -> None:
    change = DeleteBinary(Path("img.png"), Path("/tmp/f"), False)
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("delete" in line for line in lines)


def test_render_title_delete_symlink() -> None:
    change = DeleteSymlink(Path("link"), Path("/target"))
    drawable = render_change_title(change, selected=False, included=None, renames={})
    lines = render_plain(drawable)
    assert any("delete" in line for line in lines)
    assert any("symlink" in line for line in lines)


# --- render_change dispatch: additional change types ---


def test_render_change_rename_opened() -> None:
    change = Rename(Path("old.py"), Path("new.py"))
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("old.py" in line for line in lines)
    assert any("new.py" in line for line in lines)


def test_render_change_change_mode_opened() -> None:
    change = ChangeMode(Path("script.sh"), False, True)
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("executable" in line.lower() for line in lines)


def test_render_change_add_symlink_opened() -> None:
    change = AddSymlink(Path("link"), Path("/my/target"))
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("/my/target" in line for line in lines)


def test_render_change_modify_symlink_opened() -> None:
    change = ModifySymlink(Path("mysymlink"), Path("/old_target"), Path("/new_target"))
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("modify" in line for line in lines)
    all_text = " ".join(lines)
    assert "mysymlink" in all_text


def test_render_change_delete_symlink_opened() -> None:
    change = DeleteSymlink(Path("mysymlink"), Path("/old_target"))
    drawable = render_change(0, change, ChangeCursor(0), None, opened=True, renames={})
    lines = render_plain(drawable)
    assert any("delete" in line for line in lines)
    all_text = " ".join(lines)
    assert "mysymlink" in all_text
