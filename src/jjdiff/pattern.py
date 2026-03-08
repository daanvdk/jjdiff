import re
from dataclasses import dataclass
from pathlib import Path

type Node = Name | Wildcard


@dataclass(frozen=True)
class Name:
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Wildcard:
    pass


@dataclass(frozen=True)
class Pattern:
    nodes: tuple[Node, ...]

    @staticmethod
    def compile(pattern: str) -> "Pattern":
        if pattern.startswith("/"):
            pattern = pattern[1:]
        else:
            pattern = f"**/{pattern}"

        if pattern.endswith("/"):
            pattern = f"{pattern}**"

        nodes: list[Node] = []

        for part in pattern.split("/"):
            if part == "**":
                nodes.append(Wildcard())
                continue

            chunks: list[str] = []

            for chunk in part.split("*"):
                if chunks:
                    chunks.append(r"[^/]*")
                chunks.append(re.escape(chunk))

            nodes.append(Name(re.compile("".join(chunks))))

        return Pattern(tuple(nodes))

    def match(self, path: Path) -> bool:
        states: list[tuple[int, int]] = [(0, 0)]

        while states:
            i, j = states.pop()

            if i < len(self.nodes):
                node = self.nodes[i]
            else:
                node = None

            if j < len(path.parts):
                part = path.parts[j]
            else:
                part = None

            match node:
                case Name():
                    if part is not None and node.pattern.fullmatch(part):
                        states.append((i + 1, j + 1))
                case Wildcard():
                    states.append((i + 1, j))
                    if part is not None:
                        states.append((i, j + 1))
                case None:
                    if part is None:
                        return True

        return False
