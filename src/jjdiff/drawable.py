from abc import ABC, abstractmethod
from collections.abc import Iterator


class Drawable(ABC):
    @abstractmethod
    def base_width(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def render(self, width: int) -> Iterator[str]:
        raise NotImplementedError
