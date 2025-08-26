import os
import select
import sys

type KeyMap = dict[int, KeyMap] | str

KEY_MAP: dict[int, KeyMap] = {}


def add_key(raw_key: bytes, key: str) -> None:
    tree: dict[int, KeyMap] = KEY_MAP

    for char in raw_key[:-1]:
        subtree = tree.setdefault(char, {})
        assert isinstance(subtree, dict)
        tree = subtree

    assert raw_key[-1] not in tree
    tree[raw_key[-1]] = key


add_key(b"\x01", "ctrl+a")
add_key(b"\x03", "ctrl+c")
add_key(b"\x04", "ctrl+d")
add_key(b"\x1b[A", "up")
add_key(b"\x1b[B", "down")
add_key(b"\x1b[C", "right")
add_key(b"\x1b[D", "left")
add_key(b"\r", "enter")
add_key(b"\t", "tab")
add_key(b"\x1b[Z", "shift+tab")
add_key(b"\x1b[H", "home")
add_key(b"\x1b[F", "end")


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

    def get(self) -> str:
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

    def pop_key(self) -> str:
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
                    return key

            if isinstance(key, str):
                self.chars[: i + 1] = []
                return key

            key_map = key

        if self.chars == [0x1B] and not has_input():
            self.chars.clear()
            return "escape"

        return ""

    class CancelledError(Exception):
        pass
