from typing import Any, Callable, TYPE_CHECKING


if TYPE_CHECKING:
    from .renderer import Renderer


class Action:
    pass


class NullAction(Action):
    pass


class ExitAction(Action):
    pass


class BackAction(Action):
    def __init__(self, depth: int = 1) -> None:
        self.depth = depth


class SwapScreenAction(Action):
    def __init__(self, swap: Callable[["Renderer"], None], **params: Any) -> None:
        self.swap = swap
        self.params = params or {}


FOCUS_INPUT: bytes = b"\x80"
UNFOCUS_INPUT: bytes = b"\x81"
CTRL_C_INPUT: bytes = b"\x03"
