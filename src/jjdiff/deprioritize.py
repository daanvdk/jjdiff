from pathlib import Path

from jjdiff.change import Change, Rename

from .config import load_config


def is_path_deprioritized(path: Path) -> bool:
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


def is_change_deprioritized(change: Change) -> bool:
    if isinstance(change, Rename):
        return is_path_deprioritized(change.new_path)
    else:
        return is_path_deprioritized(change.path)
