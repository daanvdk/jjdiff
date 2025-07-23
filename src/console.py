from contextlib import ExitStack
import os
import signal
import sys
import termios
import tty


class Editor:
    width: int
    height: int
    changes: list[Change]

    def __init__(self, changes: list[Change]):
        self.width = 0
        self.height = 0
        self.changes = changes

    def draw(self) -> None:
        pass

    def handle_key(self, key: str) -> None:
        pass


def edit(changes):
    def resize_handler():
        pass

    with ExitStack() as stack:
        # setup resize signal
        prev_resize_handler = signal.signal(signal.SIGWINCH, resize_handler)
        stack.callback(signal.signal, signal.SIGWINCH, prev_resize_handler)

        # setup cbreak mode
        attrs = tty.setcbreak(sys.stdin, termios.TCSAFLUSH)
        stack.callback(termios.tcsetattr, sys.stdin, termios.TCSAFLUSH, attrs)

        self.width, self.height = os.get_terminal_size()
        self.draw()

        while True:
                


class Widget:
    pass
