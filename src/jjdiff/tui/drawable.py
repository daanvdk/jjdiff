import fcntl
import struct
import termios
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterator
from typing import Any, cast, override

type Metadata = dict[type, dict[int, list[Any]]]


def get_terminal_size_from_tty():
    # This enables us to still get the terminal size even if the program is
    # called through a subprocess and is thus not directly connected to the
    # TTY. This is needed to be able to use jjdiff as a diff-formatter.
    try:
        with open("/dev/tty") as fd:
            packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
            rows, cols = cast(tuple[int, int], struct.unpack("hhhh", packed)[:2])
            return cols, rows
    except Exception:
        return 80, 24  # Fallback


class Drawable(ABC):
    @abstractmethod
    def base_width(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def _render(self, width: int, height: int | None) -> Iterator["str | Marker[Any]"]:
        raise NotImplementedError

    def render(self, width: int, height: int | None) -> Generator[str, None, Metadata]:
        metadata: Metadata = {}
        y = 0

        for line in self._render(width, height):
            if isinstance(line, Marker):
                cls_metadata = metadata.setdefault(type(line), {})
                line_metadata = cls_metadata.setdefault(y, [])
                line_metadata.append(line.get_value())
            else:
                yield line
                y += 1

        return metadata

    def height(self, width: int, height: int | None) -> int:
        res = 0
        for _ in self.render(width, height):
            res += 1
        return res

    def print(self) -> None:
        width, _ = get_terminal_size_from_tty()
        for line in self.render(width, None):
            print(line)


class Marker[T](Drawable, ABC):
    @abstractmethod
    def get_value(self) -> T:
        raise NotImplementedError

    @override
    def base_width(self) -> int:
        return 0

    @override
    def _render(self, width: int, height: int | None) -> Iterator["str | Marker[Any]"]:
        yield self
