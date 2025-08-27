import os
import select
import sys
from typing import Literal, cast

type Key = Literal[
    "ctrl+a", "ctrl+b", "ctrl+c", "ctrl+d", "ctrl+e", "ctrl+f", "ctrl+g",
    "ctrl+z", "backspace", "tab", "ctrl+j", "enter", "escape",
    "up", "down", "right", "left",
    "shift+up", "shift+down", "shift+right", "shift+left",
    "ctrl+up", "ctrl+down", "ctrl+right", "ctrl+left",
    "home", "end", "pageup", "pagedown", "shift+tab",
    "insert", "delete",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "space", "!", '"', "#", "$", "%", "&", "'", "(", ")", "*", "+", ",", "-", ".", "/",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    ":", ";", "<", "=", ">", "?", "@",
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "[", "\\", "]", "^", "_", "`",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "{", "|", "}", "~",
]  # fmt: skip

type KeyMap = dict[int, KeyMap] | Key

KEY_MAP: dict[int, KeyMap] = {}


def add_key(raw_key: bytes, key: Key) -> None:
    tree: dict[int, KeyMap] = KEY_MAP

    for char in raw_key[:-1]:
        subtree = tree.setdefault(char, {})
        assert isinstance(subtree, dict)
        tree = subtree

    assert raw_key[-1] not in tree
    tree[raw_key[-1]] = key


# Control keys
add_key(b"\x01", "ctrl+a")
add_key(b"\x02", "ctrl+b")
add_key(b"\x03", "ctrl+c")
add_key(b"\x04", "ctrl+d")
add_key(b"\x05", "ctrl+e")
add_key(b"\x06", "ctrl+f")
add_key(b"\x07", "ctrl+g")
add_key(b"\x08", "backspace")  # ^H
add_key(b"\x09", "tab")  # Tab
add_key(b"\x0a", "ctrl+j")  # Line feed
add_key(b"\x0d", "enter")  # CR
add_key(b"\x1a", "ctrl+z")  # optional, may conflict in terminal
add_key(b" ", "space")

# Arrows
add_key(b"\x1b[A", "up")
add_key(b"\x1b[B", "down")
add_key(b"\x1b[C", "right")
add_key(b"\x1b[D", "left")
add_key(b"\x1b[1;2A", "shift+up")
add_key(b"\x1b[1;2B", "shift+down")
add_key(b"\x1b[1;2C", "shift+right")
add_key(b"\x1b[1;2D", "shift+left")
add_key(b"\x1b[1;5A", "ctrl+up")
add_key(b"\x1b[1;5B", "ctrl+down")
add_key(b"\x1b[1;5C", "ctrl+right")
add_key(b"\x1b[1;5D", "ctrl+left")

# Home/End/PgUp/PgDn
add_key(b"\x1b[H", "home")
add_key(b"\x1b[F", "end")
add_key(b"\x1b[5~", "pageup")
add_key(b"\x1b[6~", "pagedown")
add_key(b"\x1b[Z", "shift+tab")  # already in your list

# Insert/Delete
add_key(b"\x1b[2~", "insert")
add_key(b"\x1b[3~", "delete")

# Function keys F1-F12 (common modern sequences)
add_key(b"\x1bOP", "f1")
add_key(b"\x1bOQ", "f2")
add_key(b"\x1bOR", "f3")
add_key(b"\x1bOS", "f4")
add_key(b"\x1b[15~", "f5")
add_key(b"\x1b[17~", "f6")
add_key(b"\x1b[18~", "f7")
add_key(b"\x1b[19~", "f8")
add_key(b"\x1b[20~", "f9")
add_key(b"\x1b[21~", "f10")
add_key(b"\x1b[23~", "f11")
add_key(b"\x1b[24~", "f12")


def get_char() -> int:
    (char,) = os.read(sys.stdin.fileno(), 1) or b"\x04"
    return char


def has_input() -> bool:
    return bool(select.select([sys.stdin.fileno()], [], [], 0)[0])


class Keyboard:
    keys: list[str]
    chars: list[int]
    reading: bool

    def __init__(self):
        self.keys = []
        self.chars = []
        self.reading = False

    def get(self) -> Key:
        self.reading = True
        try:
            while True:
                if key := self.pop_key():
                    return key
                self.chars.append(get_char())
        finally:
            self.reading = False

    def cancel(self) -> None:
        if self.reading:
            raise Keyboard.CancelledError()

    def pop_key(self) -> Key | None:
        key_map = KEY_MAP

        for i in range(len(self.chars)):
            try:
                key = key_map[self.chars[i]]
            except KeyError:
                key = chr(self.chars[0])
                self.chars[:1] = []
                if key == "\x1b":
                    return "escape"
                else:
                    return cast(Key, key)

            if isinstance(key, str):
                self.chars[: i + 1] = []
                return key

            key_map = key

        if self.chars == [0x1B] and not has_input():
            self.chars.clear()
            return "escape"

        return None

    class CancelledError(Exception):
        pass
