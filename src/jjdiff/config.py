from functools import lru_cache
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel


class DiffConfig(BaseModel):
    deprioritize: list[str] = []


class Config(BaseModel):
    diff: DiffConfig = DiffConfig()


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


def path_deprioritized(path: Path) -> bool:
    for glob in load_config().diff.deprioritize:
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
