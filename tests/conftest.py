from collections.abc import Iterator
from unittest.mock import patch

import pytest

from jjdiff.config import Config


# Always use default config in tests


@pytest.fixture(autouse=True)
def config() -> Iterator[Config]:
    config = Config()
    with patch("jjdiff.config.load_config", return_value=config):
        yield config
