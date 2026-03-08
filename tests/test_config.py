import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jjdiff.config import Config, get_config_path


def test_keymap_maps_keys_to_commands() -> None:
    config = Config()
    keymap = config.keymap
    assert keymap["j"] == "next_cursor"
    assert keymap["k"] == "prev_cursor"
    assert keymap["space"] == "select_cursor"
    assert keymap["enter"] == "confirm"


def test_keymap_conflict_raises() -> None:
    config = Config()
    # "k" is already bound to prev_cursor; adding it to next_cursor causes a conflict
    config.keybindings.next_cursor = ["j", "k"]
    with pytest.raises(ValueError, match="conflicting"):
        _ = config.keymap


def test_get_config_path_with_xdg() -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom"}):
        result = get_config_path()
    assert result == Path("/custom/jjdiff/config.toml")


def test_get_config_path_default() -> None:
    env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
    with patch.dict(os.environ, env, clear=True):
        result = get_config_path()
    assert str(result).endswith("/.config/jjdiff/config.toml")
