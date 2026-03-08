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
    Rename,
    apply_changes,
    get_line_dependencies,
    get_path_dependencies,
    reverse_changes,
    split_changes,
)
from jjdiff.diff import diff

from .utils import DirFactory, read_spec


def test_apply_nothing(temp_dir_factory: DirFactory) -> None:
    root = temp_dir_factory({})
    apply_changes(root, [])
    assert read_spec(root) == {}


def test_add_file(temp_dir_factory: DirFactory) -> None:
    root = temp_dir_factory({})
    changes = [
        AddFile(Path("foo.txt"), [Line(None, "foo")], False),
    ]
    apply_changes(root, changes)
    assert read_spec(root) == {"foo.txt": "foo"}


def test_delete_file(temp_dir_factory: DirFactory) -> None:
    root = temp_dir_factory({"foo.txt": "foo"})
    changes = [
        DeleteFile(Path("foo.txt"), [Line("foo", None)], False),
    ]
    apply_changes(root, changes)
    assert read_spec(root) == {}


def test_modify_file(temp_dir_factory: DirFactory) -> None:
    root = temp_dir_factory({"foo.txt": "foo"})
    changes = [
        ModifyFile(Path("foo.txt"), [Line("foo", "bar")]),
    ]
    apply_changes(root, changes)
    assert read_spec(root) == {"foo.txt": "bar"}


def test_usecase(temp_dir_factory: DirFactory) -> None:
    old = temp_dir_factory({"foo.txt": "foo\nbar"})
    new = temp_dir_factory({"foo.txt": "fooo\nbaz", "bar.txt": "barrr"})

    old_to_new = diff(old, new)
    assert old_to_new == [
        AddFile(Path("bar.txt"), [Line(None, "barrr")], False),
        ModifyFile(Path("foo.txt"), [Line("foo", "fooo"), Line("bar", "baz")]),
    ]

    selection = {ChangeRef(1), LineRef(1, 1)}
    old_to_sel, sel_to_new = split_changes(old_to_new, selection)
    assert old_to_sel == [
        ModifyFile(Path("foo.txt"), [Line("foo", "foo"), Line("bar", "baz")]),
    ]
    assert sel_to_new == [
        AddFile(Path("bar.txt"), [Line(None, "barrr")], False),
        ModifyFile(Path("foo.txt"), [Line("foo", "fooo"), Line("baz", "baz")]),
    ]

    new_to_sel = list(reverse_changes(sel_to_new))
    assert new_to_sel == [
        DeleteFile(Path("bar.txt"), [Line("barrr", None)], False),
        ModifyFile(Path("foo.txt"), [Line("fooo", "foo"), Line("baz", "baz")]),
    ]

    apply_changes(new, new_to_sel)
    assert read_spec(new) == {"foo.txt": "foo\nbaz"}


# --- reverse_changes: non-file types ---


def test_reverse_changes_rename() -> None:
    changes = [Rename(Path("a.py"), Path("b.py"))]
    result = list(reverse_changes(changes))
    assert result == [Rename(Path("b.py"), Path("a.py"))]


def test_reverse_changes_change_mode() -> None:
    changes = [ChangeMode(Path("a.py"), False, True)]
    result = list(reverse_changes(changes))
    assert result == [ChangeMode(Path("a.py"), True, False)]


def test_reverse_changes_add_binary() -> None:
    changes = [AddBinary(Path("img.png"), Path("/tmp/f"), False)]
    result = list(reverse_changes(changes))
    assert result == [DeleteBinary(Path("img.png"), Path("/tmp/f"), False)]


def test_reverse_changes_modify_binary() -> None:
    changes = [ModifyBinary(Path("img.png"), Path("/tmp/old"), Path("/tmp/new"))]
    result = list(reverse_changes(changes))
    assert result == [ModifyBinary(Path("img.png"), Path("/tmp/new"), Path("/tmp/old"))]


def test_reverse_changes_delete_binary() -> None:
    changes = [DeleteBinary(Path("img.png"), Path("/tmp/f"), False)]
    result = list(reverse_changes(changes))
    assert result == [AddBinary(Path("img.png"), Path("/tmp/f"), False)]


def test_reverse_changes_symlinks() -> None:
    changes = [
        AddSymlink(Path("link1"), Path("/target1")),
        ModifySymlink(Path("link2"), Path("/old_target"), Path("/new_target")),
        DeleteSymlink(Path("link3"), Path("/target3")),
    ]
    result = list(reverse_changes(changes))
    assert DeleteSymlink(Path("link1"), Path("/target1")) in result
    assert (
        ModifySymlink(Path("link2"), Path("/new_target"), Path("/old_target")) in result
    )
    assert AddSymlink(Path("link3"), Path("/target3")) in result


# --- split_changes: non-file types ---


def test_split_changes_rename_included() -> None:
    changes = [Rename(Path("old.py"), Path("new.py"))]
    refs = {ChangeRef(0)}
    old_to_sel, sel_to_new = split_changes(changes, refs)
    assert old_to_sel == [Rename(Path("old.py"), Path("new.py"))]
    assert sel_to_new == []


def test_split_changes_rename_excluded() -> None:
    changes = [Rename(Path("old.py"), Path("new.py"))]
    refs: set = set()
    old_to_sel, sel_to_new = split_changes(changes, refs)
    assert old_to_sel == []
    assert sel_to_new == [Rename(Path("old.py"), Path("new.py"))]


# --- get_path_dependencies ---


def test_get_path_dependencies_delete_then_add() -> None:
    changes = [
        DeleteFile(Path("a.py"), [Line("x", None)], False),
        AddFile(Path("a.py"), [Line(None, "y")], False),
    ]
    deps = list(get_path_dependencies(changes))
    assert (ChangeRef(1), ChangeRef(0)) in deps


# --- get_line_dependencies ---


def test_get_line_dependencies_delete_file() -> None:
    changes = [
        DeleteFile(Path("a.py"), [Line("x", None)], False),
    ]
    deps = list(get_line_dependencies(changes))
    assert (ChangeRef(0), LineRef(0, 0)) in deps
