from pathlib import Path
from jjdiff.diff import diff, diff_lines
from jjdiff.change import AddFile, ChangeMode, DeleteFile, Line, ModifyFile

from .utils import DirFactory, ExecFile


def test_diff_lines_empty() -> None:
    assert diff_lines([], []) == []


def test_diff_lines_only_add() -> None:
    line1, line2 = diff_lines([], ["foo", "bar"])

    assert line1.status == "added"
    assert line1.old is None
    assert line1.new == "foo"

    assert line2.status == "added"
    assert line2.old is None
    assert line2.new == "bar"


def test_diff_lines_only_delete() -> None:
    line1, line2 = diff_lines(["foo", "bar"], [])

    assert line1.status == "deleted"
    assert line1.old == "foo"
    assert line1.new is None

    assert line2.status == "deleted"
    assert line2.old == "bar"
    assert line2.new is None


def test_diff_lines_changed() -> None:
    line1, line2 = diff_lines(["foo", "bar"], ["foo", "baz"])

    assert line1.status == "unchanged"
    assert line1.old == "foo"
    assert line1.new == "foo"

    assert line2.status == "changed"
    assert line2.old == "bar"
    assert line2.new == "baz"


def test_diff_files_empty(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({})
    new_dir = temp_dir_factory({})

    assert list(diff(old_dir, new_dir)) == []


def test_diff_files_add(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({})
    new_dir = temp_dir_factory({"foo.txt": "foo"})

    assert diff(old_dir, new_dir) == [
        AddFile(Path("foo.txt"), [Line(None, "foo")], False),
    ]


def test_diff_files_delete(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"foo.txt": "foo"})
    new_dir = temp_dir_factory({})

    assert diff(old_dir, new_dir) == [
        DeleteFile(Path("foo.txt"), [Line("foo", None)], False),
    ]


def test_diff_files_modify(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"foo.txt": "foo"})
    new_dir = temp_dir_factory({"foo.txt": "bar"})

    assert diff(old_dir, new_dir) == [
        ModifyFile(Path("foo.txt"), [Line("foo", None), Line(None, "bar")]),
    ]


def test_diff_files_modify_similar(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"bar.txt": "bar"})
    new_dir = temp_dir_factory({"bar.txt": "baz"})

    assert diff(old_dir, new_dir) == [
        ModifyFile(Path("bar.txt"), [Line("bar", "baz")]),
    ]


def test_diff_files_modify_is_exec(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"foo.txt": "foo"})
    new_dir = temp_dir_factory({"foo.txt": ExecFile("foo")})

    assert diff(old_dir, new_dir) == [
        ChangeMode(Path("foo.txt"), False, True),
    ]
