import argparse
import sys
import time

from vtpy import SerialTerminal, Terminal, TerminalException
from client import Client, Timeline
from clip import BoundingRectangle
from text import ControlCodes, display, highlight, sanitize, wordwrap

from typing import Any, Dict, List, Optional, Sequence, Tuple


class Action:
    pass


class NullAction(Action):
    pass


class ExitAction(Action):
    pass


class Component:
    def __init__(self, terminal: Terminal, client: Client, top: int, bottom: int) -> None:
        self.terminal = terminal
        self.client = client
        self.top = top
        self.bottom = bottom
        self.rows = (bottom - top) + 1

    def scrollUp(self) -> None:
        pass

    def scrollDown(self) -> None:
        pass

    def pageUp(self) -> None:
        pass

    def pageDown(self) -> None:
        pass

    def goToTop(self) -> None:
        pass

    def goToBottom(self) -> None:
        pass

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        return None


def boxtop(width: int) -> Tuple[str, List[ControlCodes]]:
    return (
        ("\u250C" + ("\u2500" * (width - 2)) + "\u2510"),
        [ControlCodes(bold=False, underline=False, reverse=False)] * width,
    )


def boxbottom(width: int) -> Tuple[str, List[ControlCodes]]:
    return (
        ("\u2514" + ("\u2500" * (width - 2)) + "\u2518"),
        [ControlCodes(bold=False, underline=False, reverse=False)] * width,
    )


def boxmiddle(line: Tuple[str, Sequence[ControlCodes]], width: int) -> Tuple[str, List[ControlCodes]]:
    text = line[0][:(width - 2)]
    codes = line[1][:(width - 2)]
    if len(text) < width - 2:
        amount = (width - 2) - len(text)

        text = text + (" " * amount)
        codes = [*codes, *([ControlCodes(bold=False, underline=False, reverse=False)] * amount)]

    text = "\u2502" + text + "\u2502"
    codes = [
        ControlCodes(bold=False, underline=False, reverse=False),
        *codes,
        ControlCodes(bold=False, underline=False, reverse=False)
    ]
    return (text, codes)


class TimelinePost:
    def __init__(self, terminal: Terminal, data: Dict[str, Any]) -> None:
        self.terminal = terminal
        self.data = data

        reblog = self.data['reblog']
        if reblog:
            # First, start with the name of the reblogger.
            account = self.data['account']['display_name']
            username = self.data['account']['acct']
            boostline = highlight(f"{sanitize(account)} (@{sanitize(username)}) boosted")

            # Now, grab the original name.
            account = reblog['account']['display_name']
            username = reblog['account']['acct']
            nameline = highlight(f"<b>{sanitize(account)}</b> @{sanitize(username)}")

            content = reblog['content']
            postbody = wordwrap(content, [ControlCodes(bold=False, underline=False, reverse=False)] * len(content), terminal.columns - 2)

            # Actual contents.
            textlines = [
                boostline,
                nameline,
                *postbody,
            ]

            # Now, surround the post in a box.
            self.lines = [
                boxtop(terminal.columns),
                *[boxmiddle(line, terminal.columns) for line in textlines],
                boxbottom(terminal.columns),
            ]
        else:
            # First, start with the name of the account.
            account = self.data['account']['display_name']
            username = self.data['account']['acct']
            nameline = highlight(f"<b>{sanitize(account)}</b> @{sanitize(username)}")

            content = self.data['content']
            postbody = wordwrap(content, [ControlCodes(bold=False, underline=False, reverse=False)] * len(content), terminal.columns - 2)

            # Actual contents.
            textlines = [
                nameline,
                *postbody,
            ]

            # Now, surround the post in a box.
            self.lines = [
                boxtop(terminal.columns),
                *[boxmiddle(line, terminal.columns) for line in textlines],
                boxbottom(terminal.columns),
            ]

    @property
    def height(self) -> int:
        return len(self.lines)

    def draw(self, top: int, bottom: int, offset: int) -> None:
        bounds = BoundingRectangle(top=top, bottom=bottom, left=1, right=self.terminal.columns + 1)
        display(self.terminal, self.lines[offset:], bounds)


class TimelineComponent(Component):
    def __init__(self, terminal: Terminal, client: Client, top: int, bottom: int) -> None:
        super().__init__(terminal, client, top, bottom)

        # First, fetch the timeline.
        self.offset = 0
        self.statuses = client.fetchTimeline(Timeline.HOME)

        # Now, format each post into it's own component.
        self.posts = [TimelinePost(terminal, status) for status in self.statuses]

        # Now, draw them.
        self.draw()

    def draw(self) -> None:
        pos = -self.offset
        viewHeight = (self.bottom - self.top) + 1

        for post in self.posts:
            if pos >= viewHeight:
                # Too low below the viewport.
                break
            if pos + post.height <= 0:
                # Too high above the viewport.
                pos += post.height
                continue

            post.draw(pos + self.top, pos + self.top + post.height, 0)
            pos += post.height

    def _drawOneLine(self, line: int) -> None:
        pos = -self.offset
        viewHeight = (self.bottom - self.top) + 1

        for post in self.posts:
            if pos >= viewHeight:
                # Too low below the viewport.
                break
            if pos + post.height <= 0:
                # Too high above the viewport.
                pos += post.height
                continue

            # Figure out what line of this post we're drawing.
            offset = line - (pos + self.top)
            if offset < 0:
                # This post is below where we want to draw.
                break
            if offset >= post.height:
                # This post is above where we want to draw, we finished.
                pos += post.height
                continue

            post.draw(line, line + 1, offset)
            pos += post.height

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == Terminal.UP:
            # Scroll up one line.
            if self.offset > 0:
                self.offset -= 1

                self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                self.terminal.sendCommand(Terminal.SET_NORMAL)
                self.terminal.setScrollRegion(self.top, self.bottom)
                self.terminal.moveCursor(self.top, 1)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)
                self._drawOneLine(self.top)
                self.terminal.clearScrollRegion()
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

                return NullAction()
        elif inputVal == Terminal.DOWN:
            # Scroll down one line.
            if self.offset < 0xFFFFFFFF:
                self.offset += 1

                self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                self.terminal.sendCommand(Terminal.SET_NORMAL)
                self.terminal.setScrollRegion(self.top, self.bottom)
                self.terminal.moveCursor(self.bottom, 1)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_DOWN)
                self._drawOneLine(self.bottom)
                self.terminal.clearScrollRegion()
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

                return NullAction()

        return None


class Renderer:
    def __init__(self, terminal: Terminal, client: Client) -> None:
        self.terminal = terminal
        self.client = client

        # Also, hardcode the timeline renderer for now.
        self.components: List[Component] = [
            TimelineComponent(self.terminal, self.client, top=1, bottom=self.terminal.rows)
        ]

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        # First, try handling it with the registered components.
        for component in self.components:
            possible = component.processInput(inputVal)
            if possible:
                return possible

        # Now, handle it with our own code.
        if inputVal == b"\x03":
            return ExitAction()

        # Nothing to do
        return None


def spawnTerminal(port: str, baudrate: int, flow: bool) -> Terminal:
    print("Attempting to contact VT-100...", end="")
    sys.stdout.flush()

    while True:
        try:
            terminal = SerialTerminal(port, baudrate, flowControl=flow)
            print("SUCCESS!")

            break
        except TerminalException:
            # Wait for terminal to re-awaken.
            time.sleep(1.0)

            print(".", end="")
            sys.stdout.flush()

    return terminal


def main(server: str, port: str, baudrate: int, flow: bool) -> int:
    # First, attempt to talk to the server.
    client = Client(server)

    exiting = False
    while not exiting:
        # First, attempt to talk to the terminal, and get the current page rendering.
        terminal = spawnTerminal(port, baudrate, flow)
        renderer = Renderer(terminal, client)

        try:
            while not exiting:
                # Grab input, de-duplicate held down up/down presses so they don't queue up.
                # This can cause the entire message loop to desync as we pile up requests to
                # scroll the screen, ultimately leading in rendering issues and a crash.
                inputVal = terminal.recvInput()
                if inputVal in {Terminal.UP, Terminal.DOWN}:
                    while inputVal == terminal.peekInput():
                        terminal.recvInput()

                if inputVal:
                    action = renderer.processInput(inputVal)
                    if isinstance(action, ExitAction):
                        print("Got request to end session!")
                        exiting = True

        except TerminalException:
            # Terminal went away mid-transaction.
            print("Lost terminal, will attempt a reconnect.")

        except KeyboardInterrupt:
            print("Got request to end session!")
            exiting = True

    # Restore the screen before exiting.
    terminal.reset()

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VT-100 terminal menu")

    parser.add_argument(
        "--port",
        default="/dev/ttyUSB0",
        type=str,
        help="Serial port to open, defaults to /dev/ttyUSB0",
    )
    parser.add_argument(
        "--baud",
        default=9600,
        type=int,
        help="Baud rate to use with VT-100, defaults to 9600",
    )
    parser.add_argument(
        "--flow",
        action="store_true",
        help="Enable software-based flow control (XON/XOFF)",
    )
    parser.add_argument(
        "server",
        metavar="SERVER",
        type=str,
        help="Mastodon-compatible server to connect to",
    )
    args = parser.parse_args()

    sys.exit(main(args.server, args.port, args.baud, args.flow))
