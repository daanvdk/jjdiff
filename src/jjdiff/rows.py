from collections.abc import Iterable

from .drawable import Drawable
from .grid import Grid


class Rows(Grid):
    def __init__(self, drawables: Iterable[Drawable]):
        super().__init__(
            (1,),
            ((drawable,) for drawable in drawables),
        )
