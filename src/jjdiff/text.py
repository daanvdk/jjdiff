from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal, override

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


class Text(Drawable):
    spans: tuple[TextSpan, ...]

    def __init__(self, content: str = "", style: TextStyle = DEFAULT_TEXT_STYLE):
        self.spans = (TextSpan(content, style),)

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

        result = Text()
        result.spans = tuple(spans)
        return result

    @override
    def base_width(self) -> int:
        max_width = 0
        curr_width = 0

        for span in self.spans:
            first = True

            for part in span.content.split("\n"):
                if first:
                    first = False
                else:
                    curr_width = 0

                curr_width += len(part)
                max_width = max(max_width, curr_width)

        return max_width

    @override
    def render(self, width: int) -> Iterator[str]:
        line: list[str] = []
        x = 0
        y = 0

        def get_line() -> str:
            nonlocal x, y

            if x < width:
                filler = " " * (width - x)
                if line:
                    line.insert(-1, filler)
                else:
                    style = self.spans[-1].style
                    line.append(style.style_code)
                    line.append(filler)
                    line.append(style.reset_code)

            res = "".join(line)
            line.clear()
            x = 0
            y += 1

            return res

        for span in self.spans:
            index = 0

            if len(span.content) == 0:
                line.append(span.style.style_code)
                line.append(span.content)
                line.append(span.style.reset_code)

            while index < len(span.content):
                max_len = width - x

                try:
                    newline_index = span.content.index("\n", index, index + max_len + 1)
                except ValueError:
                    if index + max_len < len(span.content):
                        # wraps
                        content = span.content[index : index + max_len]
                        newline = True
                        index += max_len
                    else:
                        # fits
                        content = span.content[index:]
                        newline = False
                        index = len(span.content)
                else:
                    # newline
                    content = span.content[index:newline_index]
                    newline = True
                    index = newline_index + 1

                line.append(span.style.style_code)
                line.append(content)
                line.append(span.style.reset_code)
                x += len(content)

                if newline:
                    yield get_line()

        yield get_line()
