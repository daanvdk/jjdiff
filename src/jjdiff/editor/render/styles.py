from collections.abc import Mapping

from jjdiff.tui.text import TextColor

from ...change import LineStatus

STATUS_COLOR: Mapping[LineStatus, TextColor] = {
    "added": "green",
    "changed": "yellow",
    "deleted": "red",
    "unchanged": "default",
}
SELECTED_FG: Mapping[bool, TextColor] = {
    True: "white",
    False: "bright black",
}
SELECTED_BG: Mapping[bool, TextColor | None] = {
    True: "bright black",
    False: None,
}
