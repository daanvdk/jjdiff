from typing import override

from jjdiff.tui.drawable import Marker


class SelectionMarker(Marker[None]):
    @override
    def get_value(self) -> None:
        return None
