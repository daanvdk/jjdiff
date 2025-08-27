import tempfile
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from jjdiff.config import Config

from .utils import DirFactory, DirSpec, write_spec

# Always use default config in tests


@pytest.fixture(autouse=True)
def config() -> Iterator[Config]:
    config = Config()
    with patch("jjdiff.config.get_config", return_value=config):
        yield config


@pytest.fixture
def temp_dir_factory() -> Iterator[DirFactory]:
    stack = ExitStack()

    def temp_dir_factory(dir_spec: DirSpec) -> Path:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        write_spec(root, dir_spec)
        return root

    with stack:
        yield temp_dir_factory
