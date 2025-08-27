import os
import signal
import sys
import termios
import tty
from abc import ABC, abstractmethod
from contextlib import ExitStack
from types import FrameType
from typing import Final

from .drawable import Drawable
from .keyboard import Key, Keyboard
from .scroll import Scroll, State
from .text import DEFAULT_TEXT_STYLE, Text, TextStyle


class NoResult:
    pass


NO_RESULT: Final[NoResult] = NoResult()


class Console[Result](ABC):
    width: int
    height: int
    scroll_state: State
    scrollbar_style: TextStyle

    _drawable: Drawable
    _lines: list[str]
    _redraw: bool
    _rerender: bool
    _keyboard: Keyboard
    _result: Result | NoResult

    def __init__(self, scrollbar_style: TextStyle = DEFAULT_TEXT_STYLE):
        self.scroll_state = State(self.post_render)
        self.scrollbar_style = scrollbar_style
        self.width = 0
        self.height = 0

        self._drawable = Text("")
        self._lines = []
        self._redraw = True
        self._rerender = True
        self._keyboard = Keyboard()
        self._result = NO_RESULT

    @abstractmethod
    def render(self) -> Drawable:
        raise NotImplementedError

    @abstractmethod
    def handle_key(self, key: Key) -> None:
        raise NotImplementedError

    def post_render(self, _state: State) -> None:
        pass

    @property
    def lines(self) -> int:
        return len(self._lines)

    def rerender(self) -> None:
        self._rerender = True
        self.redraw()

    def redraw(self) -> None:
        self._redraw = True
        self._keyboard.cancel()

    def set_result(self, result: Result) -> None:
        self._result = result

    def _draw(self) -> None:
        if self._rerender:
            self._rerender = False
            self._drawable = Scroll(
                self.render(),
                self.scroll_state,
                self.scrollbar_style,
            )
            rerendered = True
        else:
            rerendered = False

        width, height = os.get_terminal_size()

        if rerendered or width != self.width or height != self.height:
            self.width = width
            self.height = height
            self._lines.clear()
            self._lines.extend(self._drawable.render(width, height))

        sys.stdout.write("\x1b[2J\x1b[H")
        for line in self._lines[:height]:
            sys.stdout.write(line)
            sys.stdout.write("\x1b[1E")
        sys.stdout.flush()

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
