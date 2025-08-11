from collections.abc import Iterator, Mapping
from typing import Any, Callable, cast, override

from .text import DEFAULT_TEXT_STYLE, TextStyle
from .drawable import Drawable, Marker, Metadata


SCROLLBAR_CHAR: Mapping[tuple[bool, bool], str] = {
    (False, False): " ",
    (False, True): "\u2584",
    (True, False): "\u2580",
    (True, True): "\u2588",
}


class Scroll(Drawable):
    drawable: Drawable
    state: "State"
    scrollbar_style: TextStyle

    def __init__(
        self,
        drawable: Drawable,
        state: "State",
        scrollbar_style: TextStyle = DEFAULT_TEXT_STYLE,
    ):
        self.drawable = drawable
        self.state = state
        self.scrollbar_style = scrollbar_style

    @override
    def base_width(self) -> int:
        return self.drawable.base_width()

    @override
    def _render(self, width: int, height: int | None) -> Iterator[str | Marker[Any]]:
        if height is None:
            yield from self.drawable._render(width, None)
            return

        # Render all lines
        lines: list[str] = []
        line_gen = self.drawable.render(width - 1, None)
        try:
            while True:
                lines.append(next(line_gen))
        except StopIteration as e:
            self.state.metadata = cast(Metadata, e.value)

        # Get scroll state
        self.state.lines = len(lines)
        self.state.height = height
        self.state._on_render(self.state)

        # Render part in view
        view = lines[self.state._y : self.state._y + height]
        while len(view) < height:
            view.append(" " * (width - 1))

        # Add scrollbar
        if height < len(lines):
            blocks = height * 2
            start = round(self.state._y / len(lines) * blocks)
            end = round((self.state._y + height) / len(lines) * blocks)
        else:
            start = 0
            end = 0

        for y, line in enumerate(view):
            top = start <= y * 2 < end
            bot = start <= y * 2 + 1 < end
            view[y] = (
                line
                + self.scrollbar_style.style_code
                + SCROLLBAR_CHAR[(top, bot)]
                + self.scrollbar_style.reset_code
            )

        yield from view

    class State:
        lines: int
        height: int
        metadata: Metadata

        _y: int
        _on_render: "Callable[[Scroll.State], None]"

        def __init__(self, on_render: "Callable[[Scroll.State], None]"):
            self.lines = 0
            self.height = 0
            self.metadata = {}

            self._y = 0
            self._on_render = on_render

        def scroll_to(self, start: int, end: int, *, padding: int = 5) -> None:
            y = min(max(self._y, end + padding - self.height), start - padding)
            y = max(min(y, self.lines - self.height), 0)

            self._y = y
