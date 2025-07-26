from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import ExitStack
import os
import signal
import sys
import termios
import tty
from types import FrameType
from typing import Final, cast

from jjdiff.keyboard import Keyboard

from .drawable import Drawable, Metadata
from .text import Text, TextStyle


class NoResult:
    pass


NO_RESULT: Final[NoResult] = NoResult()

SCROLLBAR_STYLE = TextStyle(fg="bright black")
SCROLLBAR_CHAR: Mapping[tuple[bool, bool], str] = {
    (False, False): " ",
    (False, True): "\u2584",
    (True, False): "\u2580",
    (True, True): "\u2588",
}


class Console[Result](ABC):
    _drawable: Drawable

    width: int
    height: int

    _y: int
    _lines: list[str]

    _redraw: bool
    _ignore_redraw: bool
    _rerender: bool
    _keyboard: Keyboard
    _result: Result | NoResult

    def __init__(self):
        self._drawable = Text("")

        self.width = 0
        self.height = 0

        self._lines = []
        self._y = 0

        self._redraw = True
        self._rerender = True
        self._keyboard = Keyboard()
        self._result = NO_RESULT

    @abstractmethod
    def render(self) -> Drawable:
        raise NotImplementedError

    @abstractmethod
    def handle_key(self, key: str) -> None:
        raise NotImplementedError

    def post_render(self, _metadata: Metadata) -> None:
        pass

    @property
    def lines(self) -> int:
        return len(self._lines)

    def rerender(self) -> None:
        self._rerender = True
        self.redraw()

    def redraw(self) -> None:
        if not self._ignore_redraw:
            self._redraw = True
            self._keyboard.cancel()

    def scroll_to(self, start: int, end: int, *, padding: int = 5) -> None:
        y = min(max(self._y, end + padding - self.height), start - padding)
        y = max(min(y, self.lines - self.height), 0)

        self._y = y
        self.redraw()

    def set_result(self, result: Result) -> None:
        self._result = result

    def _draw(self) -> None:
        if self._rerender:
            self._rerender = False
            self._drawable = self.render()
            rerendered = True
        else:
            rerendered = False

        width, self.height = os.get_terminal_size()

        if rerendered or width != self.width:
            self.width = width
            self._lines.clear()
            lines = self._drawable.render(self.width - 1)
            try:
                while True:
                    self._lines.append(next(lines))
            except StopIteration as e:
                metadata = cast(Metadata, e.value)

            self._ignore_redraw = True
            try:
                self.post_render(metadata)
            finally:
                self._ignore_redraw = False

        sys.stdout.write("\x1b[2J\x1b[H")
        for line in self._lines[self._y : self._y + self.height]:
            sys.stdout.write(line)
            sys.stdout.write("\x1b[1E")
        self._draw_scrollbar()
        sys.stdout.flush()

    def _draw_scrollbar(self) -> None:
        blocks = self.height * 2
        start = round(self._y / self.lines * blocks)
        end = round((self._y + self.height) / self.lines * blocks)

        sys.stdout.write(f"\x1b[H\x1b[{self.width - 1}C")
        sys.stdout.write(SCROLLBAR_STYLE.style_code)

        for i in range(0, blocks, 2):
            top = start <= i < end
            bot = start <= i + 1 < end
            sys.stdout.write(SCROLLBAR_CHAR[(top, bot)])
            sys.stdout.write("\x1b[1B")

        sys.stdout.write(SCROLLBAR_STYLE.reset_code)

    def run(self) -> Result:
        def on_resize(_signal: int, _frame: FrameType | None) -> None:
            self.redraw()

        with ExitStack() as stack:
            # setup resize signal
            prev_handler = signal.signal(signal.SIGWINCH, on_resize)
            stack.callback(signal.signal, signal.SIGWINCH, prev_handler)

            # setup cbreak mode
            attrs = tty.setraw(sys.stdin)
            stack.callback(termios.tcsetattr, sys.stdin, termios.TCSADRAIN, attrs)

            # hide cursor and switch to alternative buffer
            sys.stdout.write("\x1b[?25l\x1b[?1049h")
            stack.callback(write_and_flush, "\x1b[?1049l\x1b[?25h")

            # Loop until we have a result
            while isinstance(self._result, NoResult):
                # Check for draw
                if self._redraw:
                    self._redraw = False
                    self._draw()

                # Check for input
                try:
                    key = self._keyboard.get()
                except Keyboard.CancelledError:
                    pass
                else:
                    self.handle_key(key)

            return self._result


def write_and_flush(content: str) -> None:
    sys.stdout.write(content)
    sys.stdout.flush()
