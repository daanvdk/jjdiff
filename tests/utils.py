from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jjdiff.change import set_is_exec
from jjdiff.diff import Contents, File, Symlink

type FileSpec = str | bytes


@dataclass
class ExecFile:
    file: FileSpec


type DirSpec = dict[str, FileSpec | ExecFile | Path]
type DirFactory = Callable[[DirSpec], Path]


def read_spec(root: Path) -> DirSpec:
    dir_spec: DirSpec = {}

    for path, content in Contents(root).items():
        match content:
            case File(content_path, is_exec):
                try:
                    file_spec = content_path.read_text()
                except UnicodeDecodeError:
                    file_spec = content_path.read_bytes()
                if is_exec:
                    file_spec = ExecFile(file_spec)

            case Symlink(to):
                file_spec = to

        dir_spec[str(path)] = file_spec

    return dir_spec


def write_spec(root: Path, dir_spec: DirSpec) -> None:
    for path, file_spec in dir_spec.items():
        file_path = root / path
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
            set_is_exec(file_path, True)
