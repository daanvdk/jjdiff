from functools import lru_cache
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel


class Config(BaseModel):
    pass


def get_config_path() -> Path:
    try:
        xdg_config_home = Path(os.environ["XDG_CONFIG_HOME"])
    except KeyError:
        xdg_config_home = Path.home() / ".config"
    return xdg_config_home / "jjdiff" / "config.toml"


@lru_cache(1)
def load_config() -> Config:
    config_path = get_config_path()
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    else:
        return Config.model_validate(data)
