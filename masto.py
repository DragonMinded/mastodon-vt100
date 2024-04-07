import argparse
import sys
import time

from vtpy import SerialTerminal, Terminal, TerminalException
from client import Client, Timeline, BadLoginError
from clip import BoundingRectangle
from text import ControlCodes, display, highlight, html, sanitize, striplow, wordwrap

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class Action:
    pass


class NullAction(Action):
    pass


class ExitAction(Action):
    pass


class SwapScreenAction(Action):
    def __init__(self, swap: Callable[["Renderer"], None]) -> None:
        self.swap = swap


class Component:
    def __init__(self, renderer: "Renderer", top: int, bottom: int) -> None:
        self.renderer = renderer
        self.terminal = renderer.terminal
        self.client = renderer.client
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


def boxmiddle(
    line: Tuple[str, Sequence[ControlCodes]], width: int
) -> Tuple[str, List[ControlCodes]]:
    text = line[0][: (width - 2)]
    codes = line[1][: (width - 2)]
    if len(text) < width - 2:
        amount = (width - 2) - len(text)

        text = text + (" " * amount)
        codes = [
            *codes,
            *([ControlCodes(bold=False, underline=False, reverse=False)] * amount),
        ]

    text = "\u2502" + text + "\u2502"
    codes = [
        ControlCodes(bold=False, underline=False, reverse=False),
        *codes,
        ControlCodes(bold=False, underline=False, reverse=False),
    ]
    return (text, codes)


def pad(line: str, length: int) -> str:
    if len(line) >= length:
        return line[:length]
    amount = length - len(line)
    return line + (" " * amount)


def obfuscate(line: str) -> str:
    return "*" * len(line)


def join(
    chunks: List[Tuple[str, Sequence[ControlCodes]]]
) -> Tuple[str, List[ControlCodes]]:
    accum: Tuple[str, List[ControlCodes]] = ("", [])
    for chunk in chunks:
        accum = (accum[0] + chunk[0], [*accum[1], *chunk[1]])
    return accum


class TimelinePost:
    def __init__(self, renderer: "Renderer", data: Dict[str, Any]) -> None:
        self.renderer = renderer
        self.data = data

        reblog = self.data["reblog"]
        if reblog:
            # First, start with the name of the reblogger.
            account = striplow(self.data["account"]["display_name"])
            username = striplow(self.data["account"]["acct"])
            boostline = highlight(
                f"{sanitize(account)} (@{sanitize(username)}) boosted"
            )

            # Now, grab the original name.
            account = striplow(reblog["account"]["display_name"])
            username = striplow(reblog["account"]["acct"])
            nameline = highlight(f"<b>{sanitize(account)}</b> @{sanitize(username)}")

            content = striplow(reblog["content"])
            content, codes = html(content)
            postbody = wordwrap(content, codes, renderer.columns - 2)

            # Actual contents.
            textlines = [
                boostline,
                nameline,
                *postbody,
                *self.__format_attachments(reblog["media_attachments"]),
            ]

            # Now, surround the post in a box.
            self.lines = [
                boxtop(renderer.columns),
                *[boxmiddle(line, renderer.columns) for line in textlines],
                boxbottom(renderer.columns),
            ]
        else:
            # First, start with the name of the account.
            account = striplow(self.data["account"]["display_name"])
            username = striplow(self.data["account"]["acct"])
            nameline = highlight(f"<b>{sanitize(account)}</b> @{sanitize(username)}")

            content = striplow(self.data["content"])
            content, codes = html(content)
            postbody = wordwrap(content, codes, renderer.columns - 2)

            # Actual contents.
            textlines = [
                nameline,
                *postbody,
                *self.__format_attachments(self.data["media_attachments"]),
            ]

            # Now, surround the post in a box.
            self.lines = [
                boxtop(renderer.columns),
                *[boxmiddle(line, renderer.columns) for line in textlines],
                boxbottom(renderer.columns),
            ]

    def __format_attachments(
        self, attachments: List[Dict[str, Any]]
    ) -> List[Tuple[str, List[ControlCodes]]]:
        attachmentLines = []
        for attachment in attachments:
            alt = striplow(
                attachment["description"] or "no description", allow_safe=True
            )
            url = (attachment["url"] or "").split("/")[-1]
            description, codes = highlight(f"<u>{url}</u>: {alt}")

            attachmentbody = wordwrap(description, codes, self.renderer.columns - 4)
            attachmentLines += [
                boxtop(self.renderer.columns - 2),
                *[
                    boxmiddle(line, self.renderer.columns - 2)
                    for line in attachmentbody
                ],
                boxbottom(self.renderer.columns - 2),
            ]

        return attachmentLines

    @property
    def height(self) -> int:
        return len(self.lines)

    def draw(self, top: int, bottom: int, offset: int) -> None:
        bounds = BoundingRectangle(
            top=top, bottom=bottom + 1, left=1, right=self.renderer.columns + 1
        )
        display(self.renderer.terminal, self.lines[offset:], bounds)


class TimelineComponent(Component):
    def __init__(self, renderer: "Renderer", top: int, bottom: int) -> None:
        super().__init__(renderer, top, bottom)

        # First, fetch the timeline.
        self.offset = 0
        self.statuses = self.client.fetchTimeline(Timeline.HOME)
        self.renderer.status("Timeline fetched, drawing...")

        # Now, format each post into it's own component.
        self.posts = [TimelinePost(self.renderer, status) for status in self.statuses]

        # Now, draw them.
        self.draw()
        self.renderer.status("")

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

            top = pos + self.top
            bottom = top + post.height
            if bottom > self.bottom:
                bottom = self.bottom

            post.draw(top, bottom, 0)
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

            post.draw(line, line, offset)
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


class OneLineInputBox:
    def __init__(
        self, renderer: "Renderer", text: str, length: int, *, obfuscate: bool = False
    ) -> None:
        self.renderer = renderer
        self.text = text[:length]
        self.cursor = len(self.text)
        self.length = length
        self.obfuscate = obfuscate

    @property
    def lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        if self.obfuscate:
            return [highlight("<r>" + pad(obfuscate(self.text), 36) + "</r>")]
        else:
            return [highlight("<r>" + pad(self.text, 36) + "</r>")]

    def draw(self, row: int, column: int) -> None:
        bounds = BoundingRectangle(
            top=row, bottom=row + 1, left=column, right=column + self.length + 1
        )
        display(self.renderer.terminal, self.lines, bounds)
        self.renderer.terminal.moveCursor(row, column + self.cursor)

    def processInput(self, inputVal: bytes, row: int, column: int) -> Optional[Action]:
        if inputVal == Terminal.LEFT:
            if self.cursor > 0:
                self.cursor -= 1
                self.renderer.terminal.moveCursor(row, column + self.cursor)
        elif inputVal == Terminal.RIGHT:
            if self.cursor < len(self.text):
                self.cursor += 1
                self.renderer.terminal.moveCursor(row, column + self.cursor)
        elif inputVal in {Terminal.BACKSPACE, Terminal.DELETE}:
            if self.text:
                # Just subtract from input.
                if self.cursor == len(self.text):
                    # Erasing at the end of the line.
                    self.text = self.text[:-1]

                    self.cursor -= 1
                    self.draw(row, column)
                elif self.cursor == 0:
                    # Erasing at the beginning, do nothing.
                    pass
                elif self.cursor == 1:
                    # Erasing at the beginning of the line.
                    self.text = self.text[1:]

                    self.cursor -= 1
                    self.draw(row, column)
                else:
                    # Erasing in the middle of the line.
                    spot = self.cursor - 1
                    self.text = self.text[:spot] + self.text[(spot + 1) :]

                    self.cursor -= 1
                    self.draw(row, column)

            return NullAction()
        else:
            if len(self.text) < (self.length - 1):
                # If we got some unprintable character, ignore it.
                inputVal = bytes(v for v in inputVal if v >= 0x20)
                if inputVal:
                    # Just add to input.
                    char = inputVal.decode("ascii")

                    if self.cursor == len(self.text):
                        # Just appending to the input.
                        self.text += char
                        self.cursor += 1
                        self.draw(row, column)
                    else:
                        # Adding to mid-input.
                        spot = self.cursor
                        self.text = self.text[:spot] + char + self.text[spot:]
                        self.cursor += 1
                        self.draw(row, column)

            return NullAction()

        return None


class LoginComponent(Component):
    def __init__(
        self,
        renderer: "Renderer",
        top: int,
        bottom: int,
        *,
        server: str = "",
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Set up for what input we're handling.
        self.server = server
        self.username = OneLineInputBox(renderer, username, 36)
        self.password = OneLineInputBox(renderer, password, 36, obfuscate=True)

        # Set up which component we're on.
        self.component = 0 if len(username) == 0 else (1 if len(password) == 0 else 2)

        # Now, draw the components.
        self.draw()
        self.renderer.status(f"Please enter your credentials for {self.server}.")

    def __login(self) -> bool:
        # Attempt to log in.
        try:
            self.client.login(self.username.text, self.password.text)
            return True
        except BadLoginError:
            return False

    def __moveCursor(self) -> None:
        if self.component == 0:
            self.terminal.moveCursor((self.top - 1) + 7, 22 + self.username.cursor)
        elif self.component == 1:
            self.terminal.moveCursor((self.top - 1) + 10, 22 + self.password.cursor)
        elif self.component == 2:
            self.terminal.moveCursor((self.top - 1) + 13, 23)
        elif self.component == 3:
            self.terminal.moveCursor((self.top - 1) + 13, 53)

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, create the "log in" and "quit" buttons.
        login = [
            boxtop(7),
            boxmiddle(highlight("<b>login</b>" if self.component == 2 else "login"), 7),
            boxbottom(7),
        ]
        quit = [
            boxtop(6),
            boxmiddle(highlight("<b>quit</b>" if self.component == 3 else "quit"), 6),
            boxbottom(6),
        ]

        # Now, create the "middle bit" between the buttons.
        middle = highlight(pad("", 36 - 7 - 6))

        # Now, create the login box itself.
        lines = [
            boxtop(38),
            boxmiddle(highlight("Username:"), 38),
            boxmiddle(self.username.lines[0], 38),
            boxmiddle(highlight(""), 38),
            boxmiddle(highlight("Password:"), 38),
            boxmiddle(self.password.lines[0], 38),
            boxmiddle(highlight(""), 38),
            *[
                boxmiddle(join([login[x], middle, quit[x]]), 38)
                for x in range(len(login))
            ],
            boxbottom(38),
        ]

        return lines

    def __redrawButtons(self) -> None:
        lines = self.__summonBox()
        lines = lines[8:9]
        bounds = BoundingRectangle(
            top=(self.top - 1) + 13, bottom=(self.top - 1) + 14, left=21, right=59
        )
        display(self.terminal, lines, bounds)

        # Now, put the cursor back.
        self.__moveCursor()

    def draw(self) -> None:
        # First, clear the screen and draw our logo.
        for row in range(self.top, self.bottom + 1):
            self.terminal.moveCursor(row, 1)
            self.terminal.sendCommand(Terminal.CLEAR_LINE)
        self.terminal.moveCursor((self.top - 1) + 3, 11)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_TOP)
        self.terminal.sendText("Mastodon for VT-100")
        self.terminal.moveCursor((self.top - 1) + 4, 11)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_BOTTOM)
        self.terminal.sendText("Mastodon for VT-100")

        lines = self.__summonBox()
        bounds = BoundingRectangle(
            top=(self.top - 1) + 5, bottom=(self.top - 1) + 16, left=21, right=59
        )
        display(self.terminal, lines, bounds)

        # Now, put the cursor in the right spot.
        self.__moveCursor()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == Terminal.UP:
            # Go to previous component.
            if self.component > 0:
                self.component -= 1

                # Redraw prompt, in case they typed a bad username and password.
                if self.component == 1:
                    self.renderer.status(
                        f"Please enter your credentials for {self.server}."
                    )

                # We only need to redraw buttons if we left one behind.
                if self.component != 0:
                    self.__redrawButtons()
                else:
                    self.__moveCursor()

            return NullAction()
        elif inputVal == Terminal.DOWN:
            # Go to next component.
            if self.component < 3:
                self.component += 1

                # We only need to redraw buttons if we entered one.
                if self.component >= 2:
                    self.__redrawButtons()
                else:
                    self.__moveCursor()

            return NullAction()
        elif inputVal == b"\r":
            # Ignore this.
            return NullAction()
        elif inputVal == b"\t":
            # Client pressed tab.
            if self.component == 0:
                self.component += 1
                self.__moveCursor()
            elif self.component == 1:
                self.component += 1
                self.__redrawButtons()
            elif self.component == 2:
                self.component += 1
                self.__redrawButtons()
            elif self.component == 3:
                self.component = 0
                self.__redrawButtons()

                # Redraw prompt, in case they typed a bad username and password.
                self.renderer.status(
                    f"Please enter your credentials for {self.server}."
                )

            return NullAction()
        elif inputVal == b"\n":
            # Client pressed enter.
            if self.component == 0:
                self.component += 1
                self.__moveCursor()
            elif self.component == 1:
                self.component += 1
                self.__redrawButtons()
            elif self.component == 2:
                # Actually attempt to log in.
                if self.__login():
                    self.renderer.status("Login successful, fetching timeline...")

                    # Nuke our double height stuff.
                    for row in range(self.top, self.bottom + 1):
                        self.terminal.moveCursor(row, 1)
                        self.terminal.sendCommand(Terminal.CLEAR_LINE)
                    self.terminal.moveCursor(3, 1)
                    self.terminal.sendCommand(Terminal.NORMAL_SIZE)
                    self.terminal.moveCursor(4, 1)
                    self.terminal.sendCommand(Terminal.NORMAL_SIZE)
                    self.terminal.moveCursor(self.top, 1)

                    return SwapScreenAction(spawnTimelineScreen)
                else:
                    self.renderer.status("Invalid username or password!")
            elif self.component == 3:
                # Client wants out.
                return ExitAction()

            return NullAction()
        else:
            if self.component == 0:
                return self.username.processInput(inputVal, (self.top - 1) + 7, 22)
            elif self.component == 1:
                return self.password.processInput(inputVal, (self.top - 1) + 10, 22)

        return None


class Renderer:
    def __init__(self, terminal: Terminal, client: Client) -> None:
        self.terminal = terminal
        self.client = client

        # Start with no components.
        self.components: List[Component] = []
        self.lastStatus: Optional[str] = None
        self.status("")

    @property
    def rows(self) -> int:
        return self.terminal.rows - 1

    @property
    def columns(self) -> int:
        return self.terminal.columns

    def status(self, text: str) -> None:
        if text == self.lastStatus:
            return

        self.lastStatus = text
        self.terminal.sendCommand(Terminal.SAVE_CURSOR)
        self.terminal.moveCursor(self.terminal.rows, 1)
        self.terminal.sendCommand(Terminal.SET_NORMAL)
        self.terminal.sendCommand(Terminal.SET_REVERSE)
        self.terminal.sendText(pad(text, self.terminal.columns))
        self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

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


def spawnLoginScreen(
    renderer: Renderer, *, server: str = "", username: str = "", password: str = ""
) -> None:
    renderer.components = [
        LoginComponent(
            renderer,
            top=1,
            bottom=renderer.rows,
            server=server,
            username=username,
            password=password,
        )
    ]


def spawnTimelineScreen(renderer: Renderer) -> None:
    renderer.components = [TimelineComponent(renderer, top=1, bottom=renderer.rows)]


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


def main(
    server: str, username: str, password: str, port: str, baudrate: int, flow: bool
) -> int:
    # First, attempt to talk to the server.
    client = Client(server)

    exiting = False
    while not exiting:
        # First, attempt to talk to the terminal, and get the current page rendering.
        terminal = spawnTerminal(port, baudrate, flow)
        renderer = Renderer(terminal, client)
        if not renderer.components:
            spawnLoginScreen(
                renderer, server=server, username=username, password=password
            )

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
                    elif isinstance(action, SwapScreenAction):
                        action.swap(renderer)

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
    parser.add_argument(
        "username",
        metavar="USERNAME",
        nargs="?",
        type=str,
        default="",
        help="Username to pre-fill on the login screen",
    )
    parser.add_argument(
        "password",
        metavar="PASSWORD",
        nargs="?",
        type=str,
        default="",
        help="Password to pre-fill on the login screen",
    )
    args = parser.parse_args()

    sys.exit(
        main(args.server, args.username, args.password, args.port, args.baud, args.flow)
    )
