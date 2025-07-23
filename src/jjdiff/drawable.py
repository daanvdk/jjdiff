from abc import ABC, abstractmethod
from collections.abc import Iterator
import sys


class Drawable(ABC):
    @abstractmethod
    def base_width(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def render(self, width: int) -> Iterator[str]:
        raise NotImplementedError

    def draw(self, width: int, height: int) -> int:
        lines = self.render(width)
        y = 0

        while y < height and (line := next(lines, None)) is not None:
            sys.stdout.write(f"{line}\x1b[1B\x1b[{width}D")
            y += 1

        return y
