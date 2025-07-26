from abc import ABC, abstractmethod
from collections.abc import Generator, Iterator
from typing import Any, cast, override


type Metadata = dict[type, dict[int, list[Any]]]


class Drawable(ABC):
    @abstractmethod
    def base_width(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def _render(self, width: int) -> Iterator["str | Marker[Any]"]:
        raise NotImplementedError

    def render(self, width: int) -> Generator[str, None, Metadata]:
        metadata: Metadata = {}
        y = 0

        for line in self._render(width):
            if isinstance(line, Marker):
                cls_metadata = metadata.setdefault(type(line), {})
                line_metadata = cls_metadata.setdefault(y, [])
                line_metadata.append(line.get_value())
            else:
                yield line
                y += 1

        return metadata

    def height(self, width: int) -> int:
        height = 0
        for _ in self.render(width):
            height += 1
        return height


class Marker[T](Drawable, ABC):
    @abstractmethod
    def get_value(self) -> T:
        raise NotImplementedError

    @classmethod
    def get(cls, metadata: Metadata) -> dict[int, list[T]]:
        return cast(dict[int, list[T]], metadata.get(cls, {}))

    @override
    def base_width(self) -> int:
        return 0

    @override
    def _render(self, width: int) -> Iterator["str | Marker[Any]"]:
        yield self
