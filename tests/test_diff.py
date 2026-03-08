from pathlib import Path

from jjdiff.change import (
    AddBinary,
    AddFile,
    AddSymlink,
    ChangeMode,
    DeleteBinary,
    DeleteFile,
    DeleteSymlink,
    Line,
    ModifyBinary,
    ModifyFile,
    ModifySymlink,
    Rename,
)
from jjdiff.diff import diff, diff_lines

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


# Non-UTF-8 bytes that split_lines cannot decode, forcing binary treatment
BINARY = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_diff_binary_add(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({})
    new_dir = temp_dir_factory({"foo.bin": BINARY})

    changes = diff(old_dir, new_dir)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, AddBinary)
    assert change.path == Path("foo.bin")
    assert change.is_exec is False
    assert change.content_path.read_bytes() == BINARY


def test_diff_binary_delete(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"foo.bin": BINARY})
    new_dir = temp_dir_factory({})

    changes = diff(old_dir, new_dir)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, DeleteBinary)
    assert change.path == Path("foo.bin")
    assert change.is_exec is False
    assert change.content_path.read_bytes() == BINARY


def test_diff_binary_modify(temp_dir_factory: DirFactory) -> None:
    old_content = BINARY + b"\x01"
    new_content = BINARY + b"\x02"
    old_dir = temp_dir_factory({"foo.bin": old_content})
    new_dir = temp_dir_factory({"foo.bin": new_content})

    changes = diff(old_dir, new_dir)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, ModifyBinary)
    assert change.path == Path("foo.bin")
    assert change.old_content_path.read_bytes() == old_content
    assert change.new_content_path.read_bytes() == new_content


def test_diff_binary_unchanged(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"foo.bin": BINARY})
    new_dir = temp_dir_factory({"foo.bin": BINARY})

    assert diff(old_dir, new_dir) == []


def test_diff_binary_add_exec(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({})
    new_dir = temp_dir_factory({"foo.bin": ExecFile(BINARY)})

    changes = diff(old_dir, new_dir)
    assert len(changes) == 1
    change = changes[0]
    assert isinstance(change, AddBinary)
    assert change.is_exec is True


def test_diff_binary_rename(temp_dir_factory: DirFactory) -> None:
    # Identical content: similarity is 1.0 regardless of chunk boundaries,
    # so rename is always detected. Testing partial-similarity binary renames
    # would require files large enough (~50KB+) for the rolling hash to produce
    # multiple shared chunks; that is covered indirectly by the text rename tests.
    old_dir = temp_dir_factory({"old.bin": BINARY})
    new_dir = temp_dir_factory({"new.bin": BINARY})

    changes = diff(old_dir, new_dir)
    assert changes == [Rename(Path("old.bin"), Path("new.bin"))]


def test_diff_symlink_add(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({})
    new_dir = temp_dir_factory({"link": Path("target")})

    assert diff(old_dir, new_dir) == [
        AddSymlink(Path("link"), Path("target")),
    ]


def test_diff_symlink_delete(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"link": Path("target")})
    new_dir = temp_dir_factory({})

    assert diff(old_dir, new_dir) == [
        DeleteSymlink(Path("link"), Path("target")),
    ]


def test_diff_symlink_modify(temp_dir_factory: DirFactory) -> None:
    old_dir = temp_dir_factory({"link": Path("old_target")})
    new_dir = temp_dir_factory({"link": Path("new_target")})

    assert diff(old_dir, new_dir) == [
        ModifySymlink(Path("link"), Path("old_target"), Path("new_target")),
    ]


def test_diff_file_rename(temp_dir_factory: DirFactory) -> None:
    # Identical content → pure rename with no modify
    old_dir = temp_dir_factory({"old.txt": "hello\nworld\n"})
    new_dir = temp_dir_factory({"new.txt": "hello\nworld\n"})

    assert diff(old_dir, new_dir) == [
        Rename(Path("old.txt"), Path("new.txt")),
    ]


def test_diff_file_rename_with_modify(temp_dir_factory: DirFactory) -> None:
    # Enough shared lines to exceed the 0.6 similarity threshold
    old_dir = temp_dir_factory({"old.txt": "a\nb\nc\nd\nworld\n"})
    new_dir = temp_dir_factory({"new.txt": "a\nb\nc\nd\nearth\n"})

    changes = diff(old_dir, new_dir)
    assert changes[0] == Rename(Path("old.txt"), Path("new.txt"))
    assert isinstance(changes[1], ModifyFile)
    assert changes[1].path == Path("old.txt")
