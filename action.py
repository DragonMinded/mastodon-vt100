from typing import Any, Callable, Dict, TYPE_CHECKING


if TYPE_CHECKING:
    from renderer import Renderer


class Action:
    pass


class NullAction(Action):
    pass


class ExitAction(Action):
    pass


class BackAction(Action):
    pass


class SwapScreenAction(Action):
    def __init__(
        self, swap: Callable[["Renderer"], None], **params: Dict[str, Any]
    ) -> None:
        self.swap = swap
        self.params = params or {}


FOCUS_INPUT: bytes = b"\x01"
CTRL_C_INPUT: bytes = b"\x03"
