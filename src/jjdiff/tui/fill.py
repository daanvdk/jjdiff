from collections.abc import Iterator
from typing import override

from .text import DEFAULT_TEXT_STYLE, TextStyle

from .drawable import Drawable


class Fill(Drawable):
    fill: str
    style: TextStyle

    def __init__(self, fill: str = " ", style: TextStyle = DEFAULT_TEXT_STYLE):
        self.fill = fill
        self.style = style

    @override
    def base_width(self) -> int:
        return 0

    @override
    def _render(self, width: int) -> Iterator[str]:
        parts = [self.style.style_code]

        while width:
            part = self.fill[:width]
            parts.append(part)
            width -= len(part)

        parts.append(self.style.reset_code)
        yield "".join(parts)
