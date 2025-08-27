import os
import tomllib
from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import BaseModel, computed_field

from jjdiff.tui.keyboard import Key


class DiffConfig(BaseModel):
    deprioritize: list[str] = []


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


class Config(BaseModel):
    diff: DiffConfig = DiffConfig()
    format: FormatConfig = FormatConfig()
    keybindings: KeybindingsConfig = KeybindingsConfig()

    @computed_field
    @cached_property
    def keymap(self) -> dict[Key, str]:
        print("setting keymap")
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


def path_deprioritized(path: Path) -> bool:
    for glob in get_config().diff.deprioritize:
        glob = gitglob_to_shellglob(glob)
        if path.match(glob):
            return True
    return False


def gitglob_to_shellglob(glob: str) -> str:
    # git globs need a leading slash to be anchored to the root
    if glob.startswith("/"):
        glob = glob[1:]
    else:
        glob = f"**/{glob}"

    # a trailing slash should include everything in the directory
    if glob.endswith("/"):
        glob = f"{glob}**"

    return glob
