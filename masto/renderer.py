from vtpy import Terminal

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .action import Action, ExitAction, CTRL_C_INPUT
from .client import Client
from .text import pad


if TYPE_CHECKING:
    from .component import Component


class Renderer:
    def __init__(self, terminal: Terminal, client: Client) -> None:
        # Our managed objects.
        self.terminal = terminal
        self.client = client

        # Our global properties.
        self.properties: Dict[str, Any] = {}

        # Start with no components.
        self.__components: List["Component"] = []
        self.__stack: List[List["Component"]] = []
        self.__lastStatus: Optional[str] = None
        self.status("")

    def replace(self, components: List["Component"]) -> None:
        self.__components = components[:]
        self.__stack = []
        for component in self.__components:
            component.draw()

    def push(self, components: List["Component"]) -> None:
        if self.__components:
            self.__stack.append(self.__components)
        self.__components = components[:]
        for component in self.__components:
            component.draw()

    def pop(self) -> None:
        if self.__stack:
            self.__components = self.__stack[-1]
            self.__stack = self.__stack[:-1]

            for component in self.__components:
                component.draw()

    @property
    def rows(self) -> int:
        return self.terminal.rows - 1

    @property
    def columns(self) -> int:
        return self.terminal.columns

    @property
    def currentStatus(self) -> str:
        return self.__lastStatus or ""

    def status(self, text: str) -> str:
        if text == self.__lastStatus:
            return self.__lastStatus or ""

        oldStatus = self.__lastStatus

        self.__lastStatus = text
        row, col = self.terminal.fetchCursor()
        self.terminal.sendCommand(Terminal.SAVE_CURSOR)
        self.terminal.moveCursor(self.terminal.rows, 1)
        self.terminal.sendCommand(Terminal.SET_NORMAL)
        self.terminal.sendCommand(Terminal.SET_REVERSE)
        self.terminal.sendText(pad(text, self.terminal.columns))
        self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

        # Work around a bug with cursor report timing after drawing status
        # on the original VT-10X terminals.
        self.terminal.moveCursor(row, col)

        return oldStatus or ""

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        # First, try handling it with the registered components.
        for component in self.__components:
            possible = component.processInput(inputVal)
            if possible:
                return possible

        # Now, handle it with our own code.
        if inputVal == CTRL_C_INPUT:
            return ExitAction()

        # Nothing to do
        return None
