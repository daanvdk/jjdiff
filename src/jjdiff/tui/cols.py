from collections.abc import Iterable

from .drawable import Drawable
from .grid import Grid


class Cols(Grid):
    def __init__(self, drawables: Iterable[Drawable]):
        drawables = tuple(drawables)
        super().__init__(
            tuple(1 for _ in drawables),
            [drawables],
        )
