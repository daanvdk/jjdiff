from pathlib import Path

from jjdiff.pattern import Pattern


def test_pattern_plain_matches_root_level() -> None:
    # Core regression: a root-level file must match an unanchored glob
    assert Pattern.compile("*.lock").match(Path("package.lock"))


def test_pattern_plain_matches_nested() -> None:
    assert Pattern.compile("*.lock").match(Path("vendor/package.lock"))


def test_pattern_anchored_matches_root() -> None:
    assert Pattern.compile("/foo.py").match(Path("foo.py"))


def test_pattern_anchored_does_not_match_nested() -> None:
    assert not Pattern.compile("/foo.py").match(Path("src/foo.py"))


def test_pattern_directory_matches_nested() -> None:
    assert Pattern.compile("src/").match(Path("a/b/src/file.py"))


def test_pattern_anchored_directory_matches() -> None:
    assert Pattern.compile("/src/").match(Path("src/file.py"))


def test_pattern_anchored_directory_does_not_match_nested_src() -> None:
    assert not Pattern.compile("/src/").match(Path("a/src/file.py"))
