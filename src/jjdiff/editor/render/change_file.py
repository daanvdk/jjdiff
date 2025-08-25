from difflib import SequenceMatcher

from jjdiff.config import load_config
from jjdiff.tui.drawable import Drawable
from jjdiff.tui.fill import Fill
from jjdiff.tui.grid import Grid
from jjdiff.tui.rows import Rows
from jjdiff.tui.text import Text, TextStyle

from ...change import (
    Line,
    LineRef,
    LineStatus,
    Ref,
)
from ..cursor import Cursor
from .markers import SelectionMarker
from .styles import SELECTED_BG, SELECTED_FG, STATUS_COLOR

MIN_CONTEXT = 3
MIN_OMITTED = 2


def render_change_file(
    change_index: int,
    lines: list[Line],
    cursor: Cursor | None,
    included: set[Ref] | None = None,
    line_nums: bool = True,
) -> Drawable:
    drawables: list[Drawable] = []
    ranges: list[tuple[int, int]] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1

        if line.status == "unchanged":
            continue

        start = max(index - MIN_CONTEXT, 0)

        while index < len(lines) and lines[index].status != "unchanged":
            index += 1

        end = min(index + MIN_CONTEXT, len(lines))

        if ranges and start - ranges[-1][1] < MIN_OMITTED:
            start, _ = ranges.pop()

        ranges.append((start, end))

    index = 0
    old_line = 1
    new_line = 1

    for start, end in ranges:
        if index < start:
            for line in lines[index:start]:
                if line.old is not None:
                    old_line += 1
                if line.new is not None:
                    new_line += 1

            drawables.append(
                render_omitted(
                    start - index,
                    cursor is not None and cursor.is_all_lines_selected(change_index),
                )
            )
        else:
            assert index == start, repr(ranges)

        rows: list[tuple[Drawable, ...]] = []

        for line_index, line in enumerate(lines[start:end], start):
            selected = cursor is not None and cursor.is_line_selected(
                change_index, line_index
            )
            if included is None:
                line_included = None
            else:
                line_included = LineRef(change_index, line_index) in included

            underline_old: list[tuple[int, int]] = []
            underline_new: list[tuple[int, int]] = []

            if line.old is not None and line.new is not None:
                for op, old_start, old_end, new_start, new_end in SequenceMatcher(
                    None, line.old, line.new
                ).get_opcodes():
                    if op == "delete" or op == "replace":
                        underline_old.append((old_start, old_end))
                    if op == "insert" or op == "replace":
                        underline_new.append((new_start, new_end))

            old_line_status: LineStatus
            new_line_status: LineStatus

            if line.status == "changed":
                old_line_status = "deleted"
                new_line_status = "added"
            else:
                old_line_status = line.status
                new_line_status = line.status

            if selected:
                rows.append((SelectionMarker(), Rows(), Rows(), Rows()))

            rows.append(
                (
                    *render_line(
                        old_line,
                        old_line_status,
                        line.old,
                        selected,
                        line_included,
                        underline_old,
                        line_nums,
                    ),
                    *render_line(
                        new_line,
                        new_line_status,
                        line.new,
                        selected,
                        line_included,
                        underline_new,
                        line_nums,
                    ),
                )
            )

            if line.old is not None:
                old_line += 1
            if line.new is not None:
                new_line += 1

        drawables.append(Grid((None, 1, None, 1), rows))
        index = end

    if index < len(lines):
        drawables.append(
            render_omitted(
                len(lines) - index,
                cursor is not None and cursor.is_all_lines_selected(change_index),
            )
        )

    return Rows(drawables)


def render_omitted(lines: int, selected: bool) -> Drawable:
    if lines == 1:
        plural = ""
    else:
        plural = "s"

    style = TextStyle(fg=SELECTED_FG[selected], bg=SELECTED_BG[selected])

    return Grid(
        (1, None, 1),
        [
            (
                Fill("\u2500", style),
                Text(f" omitted {lines} unchanged line{plural} ", style),
                Fill("\u2500", style),
            )
        ],
    )


def render_line(
    line: int,
    status: LineStatus,
    content: str | None,
    selected: bool,
    included: bool | None,
    underline: list[tuple[int, int]],
    line_nums: bool,
) -> tuple[Drawable, Drawable]:
    gutter: Drawable
    drawable: Drawable

    if line_nums:
        line_num = format(line, ">4")
    else:
        line_num = " " * 4

    if content is None:
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text("\u258f" + "\u2571" * 6, TextStyle(fg=fg, bg=bg))
        gutter_padding = gutter
        drawable = Fill("\u2571", TextStyle(fg=fg, bg=bg))
        drawable_padding = drawable

    elif status == "unchanged":
        fg = SELECTED_FG[selected]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258f {line_num} ", TextStyle(fg=fg, bg=bg))
        gutter_padding = Text("\u258f      ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(bg=bg))
        drawable_padding = Fill(" ", TextStyle(bg=bg))

    elif included is True:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text.join(
            [
                Text(f" \u2713{line_num}", TextStyle(fg="black", bg=fg, bold=True)),
                Text("\u258c", TextStyle(fg=fg, bg=bg)),
            ]
        )
        gutter_padding = Text.join(
            [
                Text("      ", TextStyle(fg="black", bg=fg, bold=True)),
                Text("\u258c", TextStyle(fg=fg, bg=bg)),
            ]
        )

        drawable = render_line_content(
            content,
            underline,
            TextStyle(fg=fg, bg=bg, bold=True, italic=True),
        )
        drawable_padding = Fill(" ", TextStyle(bg=bg))

    elif included is False:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258c\u2717{line_num} ", TextStyle(fg=fg, bg=bg))
        gutter_padding = Text("\u258c      ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(fg=fg, bg=bg))
        drawable_padding = Fill(" ", TextStyle(bg=bg))

    else:
        fg = STATUS_COLOR[status]
        bg = SELECTED_BG[selected]

        gutter = Text(f"\u258c {line_num} ", TextStyle(fg=fg, bg=bg))
        gutter_padding = Text("\u258c      ", TextStyle(fg=fg, bg=bg))
        drawable = render_line_content(content, underline, TextStyle(fg=fg, bg=bg))
        drawable_padding = Fill(" ", TextStyle(bg=bg))

    return Grid.Cell(gutter, gutter_padding), Grid.Cell(drawable, drawable_padding)


def render_line_content(
    content: str,
    underline: list[tuple[int, int]],
    style: TextStyle,
) -> Text:
    underlined_style = style.update(underline=True)

    texts: list[Text] = []
    index = 0

    for start, end in underline:
        texts.append(Text(normalize_text(content[index:start]), style))
        texts.append(Text(normalize_text(content[start:end]), underlined_style))
        index = end
    texts.append(Text(normalize_text(content[index:]), style))

    return Text.join(texts)


def normalize_text(line: str) -> str:
    tab_repl = " " * load_config().format.tab_width
    return line.replace("\r", "").replace("\t", tab_repl)
