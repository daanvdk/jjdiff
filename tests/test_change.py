from pathlib import Path

from jjdiff.change import (
    AddFile,
    ChangeRef,
    DeleteFile,
    Line,
    LineRef,
    ModifyFile,
    apply_changes,
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
