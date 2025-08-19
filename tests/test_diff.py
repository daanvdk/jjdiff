from pathlib import Path
from jjdiff.diff import Content, File, diff_contents, diff_lines
from jjdiff.change import AddFile, ChangeMode, DeleteFile, Line, ModifyFile


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


def test_diff_files_empty() -> None:
    assert list(diff_contents({}, {})) == []


def test_diff_files_add() -> None:
    old_contents: dict[Path, Content] = {}
    new_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["foo"], False),
    }

    assert diff_contents(old_contents, new_contents) == [
        AddFile(Path("foo.txt"), [Line(None, "foo")], False, False),
    ]


def test_diff_files_delete() -> None:
    old_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["foo"], False),
    }
    new_contents: dict[Path, Content] = {}

    assert diff_contents(old_contents, new_contents) == [
        DeleteFile(Path("foo.txt"), [Line("foo", None)], False, False),
    ]


def test_diff_files_modify() -> None:
    old_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["foo"], False),
    }
    new_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["bar"], False),
    }

    assert diff_contents(old_contents, new_contents) == [
        ModifyFile(Path("foo.txt"), [Line("foo", None), Line(None, "bar")], False),
    ]


def test_diff_files_modify_similar() -> None:
    old_contents: dict[Path, Content] = {
        Path("bar.txt"): File(["bar"], False),
    }
    new_contents: dict[Path, Content] = {
        Path("bar.txt"): File(["baz"], False),
    }

    assert diff_contents(old_contents, new_contents) == [
        ModifyFile(Path("bar.txt"), [Line("bar", "baz")], False),
    ]


def test_diff_files_modify_is_exec() -> None:
    old_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["foo"], False),
    }
    new_contents: dict[Path, Content] = {
        Path("foo.txt"): File(["foo"], True),
    }

    assert diff_contents(old_contents, new_contents) == [
        ChangeMode(Path("foo.txt"), False, True, False),
    ]
