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
from jjdiff.diff import (
    Section,
    _myers_keep_sections,
    _similarity_diff,
    diff,
    diff_lines,
)

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


# --- _myers_keep_sections ---


def test_myers_keep_sections_identical() -> None:
    sections = _myers_keep_sections(["a", "b", "c"], ["a", "b", "c"])
    assert sections == [Section(0, 3, 0, 3)]


def test_myers_keep_sections_no_common() -> None:
    assert _myers_keep_sections(["a", "b"], ["c", "d"]) == []


def test_myers_keep_sections_common_prefix() -> None:
    sections = _myers_keep_sections(["a", "b", "old"], ["a", "b", "new"])
    assert sections == [Section(0, 2, 0, 2)]


def test_myers_keep_sections_common_suffix() -> None:
    sections = _myers_keep_sections(["old", "a", "b"], ["new", "a", "b"])
    assert sections == [Section(1, 3, 1, 3)]


def test_myers_keep_sections_common_middle() -> None:
    sections = _myers_keep_sections(
        ["old1", "common", "old2"], ["new1", "common", "new2"]
    )
    assert sections == [Section(1, 2, 1, 2)]


def test_myers_keep_sections_empty() -> None:
    assert _myers_keep_sections([], []) == []


def test_myers_keep_sections_insertion() -> None:
    sections = _myers_keep_sections(["a", "b"], ["a", "x", "b"])
    assert sections == [Section(0, 1, 0, 1), Section(1, 2, 2, 3)]


# --- _similarity_diff ---


def test_similarity_diff_only_deletes() -> None:
    # More old than new: extra old lines must produce "delete" ops
    ops = _similarity_diff(["foobar", "extra"], ["foobaz"], 0, 2, 0, 1)
    assert ops.count("delete") == 1
    assert ops.count("add") == 0
    assert ops.count("change") == 1


def test_similarity_diff_only_adds() -> None:
    # More new than old: extra new lines must produce "add" ops
    ops = _similarity_diff(["foobaz"], ["foobar", "extra"], 0, 1, 0, 2)
    assert ops.count("add") == 1
    assert ops.count("delete") == 0
    assert ops.count("change") == 1


def test_similarity_diff_dissimilar_no_change() -> None:
    # "aaa" vs "bbb" have 0 similarity: only delete + add, no change
    ops = _similarity_diff(["aaa"], ["bbb"], 0, 1, 0, 1)
    assert "change" not in ops
    assert "delete" in ops
    assert "add" in ops


def test_similarity_diff_similar_produces_change() -> None:
    # "foobar" vs "foobaz" share enough chars (similarity ≈ 0.83 > 0.6)
    ops = _similarity_diff(["foobar"], ["foobaz"], 0, 1, 0, 1)
    assert ops == ["change"]


# --- diff_lines: _similarity_diff integration ---


def test_diff_lines_replace_more_old_than_new() -> None:
    # "foobar"/"foobaz" are similar and pair as a change; "extra" has no match → deleted
    result = diff_lines(["foobar", "extra"], ["foobaz"])
    assert result == [Line("foobar", "foobaz"), Line("extra", None)]


def test_diff_lines_replace_more_new_than_old() -> None:
    result = diff_lines(["foobaz"], ["foobar", "extra"])
    assert result == [Line("foobaz", "foobar"), Line(None, "extra")]


def test_diff_lines_similar_pairs_matched_in_order() -> None:
    # Both pairs are mutually similar; they should pair in order, not cross-match
    result = diff_lines(["foo aaa", "foo bbb"], ["foo aab", "foo bbc"])
    assert result == [Line("foo aaa", "foo aab"), Line("foo bbb", "foo bbc")]


def test_diff_lines_dissimilar_not_paired() -> None:
    # "aaa" and "bbb" share no characters (similarity 0 < 0.6): delete then add
    result = diff_lines(["aaa"], ["bbb"])
    assert result == [Line("aaa", None), Line(None, "bbb")]


def test_diff_lines_keeps_unchanged_context() -> None:
    # Lines identical before and after the change must remain unchanged
    result = diff_lines(
        ["header", "old body", "footer"], ["header", "new body", "footer"]
    )
    assert result[0] == Line("header", "header")
    assert result[0].status == "unchanged"
    assert result[-1] == Line("footer", "footer")
    assert result[-1].status == "unchanged"


def test_diff_lines_keeps_with_leading_whitespace() -> None:
    # Myers strips leading whitespace: "  foo" and "foo" match in the first pass
    result = diff_lines(["  foo", "bar"], ["foo", "bar"])
    assert len(result) == 2
    assert result[0] == Line("  foo", "foo")
    assert result[1] == Line("bar", "bar")
