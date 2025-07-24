from abc import ABC, abstractmethod
from collections.abc import Iterator


class Drawable(ABC):
    @abstractmethod
    def base_width(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def render(self, width: int) -> Iterator[str]:
        raise NotImplementedError

    def height(self, width: int) -> int:
        height = 0
        for _ in self.render(width):
            height += 1
        return height
