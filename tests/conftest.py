from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
import stat
from unittest.mock import patch
import tempfile

import pytest

from jjdiff.config import Config

from .types import ExecFile, TempDirSpec, TempDirFactory


# Always use default config in tests


@pytest.fixture(autouse=True)
def config() -> Iterator[Config]:
    config = Config()
    with patch("jjdiff.config.load_config", return_value=config):
        yield config


@pytest.fixture
def temp_dir_factory() -> Iterator[TempDirFactory]:
    stack = ExitStack()

    def temp_dir_factory(dir_spec: TempDirSpec) -> Path:
        dir_path = Path(stack.enter_context(tempfile.TemporaryDirectory()))

        for path, file_spec in dir_spec.items():
            file_path = dir_path / path
            file_path.parent.mkdir(exist_ok=True, parents=True)

            if isinstance(file_spec, ExecFile):
                file_spec = file_spec.file
                is_exec = True
            else:
                is_exec = False

            match file_spec:
                case str():
                    file_path.write_text(file_spec)
                case bytes():
                    file_path.write_bytes(file_spec)
                case Path():
                    file_path.symlink_to(file_spec)

            if is_exec:
                file_path.chmod(file_path.stat().st_mode | stat.S_IXUSR)

        return dir_path

    with stack:
        yield temp_dir_factory
