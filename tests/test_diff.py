from jjdiff.diff import diff_lines


def test_diff_lines_empty():
    assert diff_lines([], []) == []


def test_diff_lines_only_add():
    line1, line2 = diff_lines([], ["foo", "bar"])

    assert line1.status == "added"
    assert line1.old is None
    assert line1.new == "foo"

    assert line2.status == "added"
    assert line2.old is None
    assert line2.new == "bar"


def test_diff_lines_only_delete():
    line1, line2 = diff_lines(["foo", "bar"], [])

    assert line1.status == "deleted"
    assert line1.old == "foo"
    assert line1.new is None

    assert line2.status == "deleted"
    assert line2.old == "bar"
    assert line2.new is None


def test_diff_lines_changed():
    line1, line2 = diff_lines(["foo", "bar"], ["foo", "baz"])

    assert line1.status == "unchanged"
    assert line1.old == "foo"
    assert line1.new == "foo"

    assert line2.status == "changed"
    assert line2.old == "bar"
    assert line2.new == "baz"
