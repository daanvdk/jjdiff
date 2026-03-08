import os
import tomllib
from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import BaseModel, computed_field

from .pattern import Pattern
from .tui.keyboard import Key


class DiffConfig(BaseModel):
    deprioritize: list[str] = []


class EditorConfig(BaseModel):
    default_open: bool = False
    auto_open: bool = False


class FormatConfig(BaseModel):
    tab_width: int = 4


class KeybindingsConfig(BaseModel):
    exit: list[Key] = ["escape", "ctrl+c", "ctrl+d"]
    next_cursor: list[Key] = ["j", "down", "tab"]
    prev_cursor: list[Key] = ["k", "up", "shift+tab"]
    first_cursor: list[Key] = ["g", "home"]
    last_cursor: list[Key] = ["G", "end"]
    shrink_cursor: list[Key] = ["l", "right"]
    grow_cursor: list[Key] = ["h", "left"]
    select_cursor: list[Key] = ["space"]
    select_all: list[Key] = ["a", "ctrl+a"]
    confirm: list[Key] = ["enter"]
    undo: list[Key] = ["u"]
    redo: list[Key] = ["U"]
    open_all: list[Key] = ["o"]
    close_all: list[Key] = ["O"]


class Config(BaseModel):
    diff: DiffConfig = DiffConfig()
    editor: EditorConfig = EditorConfig()
    format: FormatConfig = FormatConfig()
    keybindings: KeybindingsConfig = KeybindingsConfig()

    @computed_field
    @cached_property
    def keymap(self) -> dict[Key, str]:
        keymap: dict[Key, str] = {}

        for command in KeybindingsConfig.model_fields:
            for key in getattr(self.keybindings, command):
                try:
                    prev_command = keymap[key]
                except KeyError:
                    pass
                else:
                    raise ValueError(
                        f"conflicting commands for key {key!r}: {prev_command} and {command}"
                    )
                keymap[key] = command

        return keymap

    @computed_field
    @cached_property
    def deprioritize_patterns(self) -> list[Pattern]:
        return list(map(Pattern.compile, self.diff.deprioritize))


def get_config_path() -> Path:
    try:
        xdg_config_home = Path(os.environ["XDG_CONFIG_HOME"])
    except KeyError:
        xdg_config_home = Path.home() / ".config"
    return xdg_config_home / "jjdiff" / "config.toml"


@lru_cache(1)
def get_config() -> Config:
    config_path = get_config_path()
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    else:
        return Config.model_validate(data)


def is_path_deprioritized(path: Path) -> bool:
    return any(pattern.match(path) for pattern in get_config().deprioritize_patterns)
