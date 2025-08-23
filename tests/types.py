from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

type TempFileSpec = str | bytes


@dataclass
class ExecFile:
    file: TempFileSpec


type TempDirSpec = dict[str, TempFileSpec | ExecFile | Path]
type TempDirFactory = Callable[[TempDirSpec], Path]
