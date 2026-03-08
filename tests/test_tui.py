import re

from jjdiff.tui.cols import Cols
from jjdiff.tui.drawable import Drawable
from jjdiff.tui.fill import Fill
from jjdiff.tui.grid import Grid
from jjdiff.tui.rows import Rows
from jjdiff.tui.text import Text

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def render_plain(drawable: Drawable, width: int = 40) -> list[str]:
    lines = list(drawable.render(width, None))
    return [ANSI_ESCAPE.sub("", line) for line in lines]


# --- Text ---


def test_text_empty() -> None:
    lines = render_plain(Text(""), width=5)
    assert len(lines) == 1
    assert lines[0].strip() == ""


def test_text_simple() -> None:
    lines = render_plain(Text("hello"), width=10)
    assert len(lines) == 1
    assert "hello" in lines[0]


def test_text_wrap() -> None:
    lines = render_plain(Text("hello world"), width=5)
    assert len(lines) > 1


def test_text_concat() -> None:
    result = Text("a") + Text("b")
    lines = render_plain(result, width=10)
    assert lines[0].strip() == "ab"


def test_text_join() -> None:
    result = Text.join([Text("a"), Text("b")], Text(", "))
    lines = render_plain(result, width=10)
    assert "a, b" in lines[0]


def test_text_join_no_separator() -> None:
    result = Text.join([Text("foo"), Text("bar")])
    lines = render_plain(result, width=10)
    assert "foobar" in lines[0]


# --- Rows ---


def test_rows_stacks_vertically() -> None:
    rows = Rows([Text("line1"), Text("line2")])
    lines = render_plain(rows, width=10)
    assert len(lines) == 2
    assert "line1" in lines[0]
    assert "line2" in lines[1]


def test_rows_empty() -> None:
    rows = Rows([])
    lines = render_plain(rows, width=10)
    assert len(lines) == 0


# --- Cols ---


def test_cols_side_by_side() -> None:
    cols = Cols([Text("hi"), Text("world")])
    lines = render_plain(cols, width=20)
    assert len(lines) == 1
    assert "hi" in lines[0]
    assert "world" in lines[0]


# --- Fill ---


def test_fill_fills_width() -> None:
    lines = render_plain(Fill("-"), width=10)
    assert len(lines) == 1
    assert lines[0] == "-" * 10


def test_fill_default_spaces() -> None:
    lines = render_plain(Fill(), width=5)
    assert len(lines) == 1
    assert lines[0] == " " * 5


def test_fill_height_zero() -> None:
    lines = list(Fill("-").render(10, 0))
    assert len(lines) == 0


def test_fill_height_one() -> None:
    lines = list(Fill("-").render(5, 1))
    assert len(lines) == 1


# --- Drawable.height ---


def test_drawable_height() -> None:
    assert Text("line1\nline2\nline3").height(40, None) == 3


# --- Grid.base_width with fixed columns ---


def test_grid_base_width_fixed_columns() -> None:
    # columns=(None, 1): first column is fixed-width, second is weighted
    # The fixed column contains Text("hello") with base_width 5
    grid = Grid(columns=(None, 1), rows=[(Text("hello"), Text("x"))])
    assert grid.base_width() == 5
