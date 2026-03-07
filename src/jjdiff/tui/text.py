from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, overload, override

from wcwidth import wcswidth

if TYPE_CHECKING:

    def graphemes(_: str) -> Iterator[str]: ...
else:
    from grapheme import graphemes  # type: ignore[import-untyped]


from .drawable import Drawable

type TextColor = Literal[
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "default",
    "bright black",
    "bright red",
    "bright green",
    "bright yellow",
    "bright blue",
    "bright magenta",
    "bright cyan",
    "bright white",
]

FG_CODES: Mapping[TextColor, str] = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "default": "39",
    "bright black": "90",
    "bright red": "91",
    "bright green": "92",
    "bright yellow": "93",
    "bright blue": "94",
    "bright magenta": "95",
    "bright cyan": "96",
    "bright white": "97",
}

BG_CODES: Mapping[TextColor, str] = {
    "black": "40",
    "red": "41",
    "green": "42",
    "yellow": "43",
    "blue": "44",
    "magenta": "45",
    "cyan": "46",
    "white": "47",
    "default": "49",
    "bright black": "100",
    "bright red": "101",
    "bright green": "102",
    "bright yellow": "103",
    "bright blue": "104",
    "bright magenta": "105",
    "bright cyan": "106",
    "bright white": "107",
}


@dataclass
class TextStyle:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    fg: TextColor | None = None
    bg: TextColor | None = None

    @property
    def style_code(self) -> str:
        codes: list[str] = []

        if self.bold:
            codes.append("1")
        if self.italic:
            codes.append("3")
        if self.underline:
            codes.append("4")
        if self.fg is not None:
            codes.append(FG_CODES[self.fg])
        if self.bg is not None:
            codes.append(BG_CODES[self.bg])

        if not codes:
            return ""

        return "\x1b[" + ";".join(codes) + "m"

    @property
    def reset_code(self) -> str:
        if self.style_code:
            return "\x1b[0m"
        else:
            return ""

    def update(
        self,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        fg: TextColor | None = None,
        bg: TextColor | None = None,
    ) -> "TextStyle":
        if bold is None:
            bold = self.bold

        if italic is None:
            italic = self.italic

        if underline is None:
            underline = self.underline

        if fg is None:
            fg = self.fg

        if bg is None:
            bg = self.bg

        return TextStyle(bold, italic, underline, fg, bg)


DEFAULT_TEXT_STYLE = TextStyle()


@dataclass
class TextSpan:
    content: str
    style: TextStyle

    def __post_init__(self) -> None:
        assert "\t" not in self.content
        assert "\r" not in self.content


class Text(Drawable):
    spans: tuple[TextSpan, ...]

    @overload
    def __init__(
        self, content: str = "", style: TextStyle = DEFAULT_TEXT_STYLE
    ) -> None: ...
    @overload
    def __init__(self, content: tuple[TextSpan, ...]) -> None: ...
    def __init__(
        self,
        content: str | tuple[TextSpan, ...] = "",
        style: TextStyle = DEFAULT_TEXT_STYLE,
    ) -> None:
        if isinstance(content, str):
            content = (TextSpan(content, style),)
        self.spans = content

    def __add__(self, other: "Text") -> "Text":
        return Text.join([self, other])

    @staticmethod
    def join(
        texts: Iterable["Text"],
        joiner: "Text | None" = None,
    ) -> "Text":
        spans: list[TextSpan] = []

        for i, text in enumerate(texts):
            if i != 0 and joiner is not None:
                spans.extend(joiner.spans)
            spans.extend(text.spans)

        return Text(tuple(spans))

    @override
    def base_width(self) -> int:
        max_width = 0
        curr_width = 0

        for span in self.spans:
            for cluster in graphemes(span.content):
                if cluster == "\n":
                    max_width = max(max_width, curr_width)
                    curr_width = 0
                    continue

                cluster_width = wcswidth(cluster)
                if cluster_width < 0:
                    cluster_width = 1

                curr_width += cluster_width

        return max(max_width, curr_width)

    @override
    def _render(self, width: int, height: int | None) -> Iterator[str]:
        curr_span = TextSpan("", DEFAULT_TEXT_STYLE)
        curr_line: list[str] = []
        curr_style = DEFAULT_TEXT_STYLE
        x = 0

        def ensure_style(style: TextStyle) -> None:
            nonlocal curr_style

            if curr_style != style:
                curr_line.append(curr_style.reset_code)
                curr_style = style
                curr_line.append(curr_style.style_code)

        def flush_line() -> str:
            nonlocal curr_span, curr_style, x

            if x < width:
                ensure_style(curr_span.style)
                curr_line.extend(" " for _ in range(x, width))
            curr_line.append(curr_style.reset_code)
            line = "".join(curr_line)

            curr_line.clear()
            curr_style = DEFAULT_TEXT_STYLE
            x = 0

            return line

        for curr_span in self.spans:
            for cluster in graphemes(curr_span.content):
                # Handle newline
                if cluster == "\n":
                    yield flush_line()
                    continue

                cluster_width = wcswidth(cluster)

                # Handle characters that are not renderable or will never fit
                if cluster_width < 0 or cluster_width > width:
                    cluster = "?"
                    cluster_width = 1

                # Handle line wrap if character does not fit
                if x + cluster_width > width:
                    yield flush_line()

                ensure_style(curr_span.style)
                curr_line.append(cluster)
                x += cluster_width

        yield flush_line()
