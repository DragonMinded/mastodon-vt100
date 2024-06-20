import argparse
import sys
import time

from vtpy import SerialTerminal, Terminal, TerminalException

from .action import BackAction, ExitAction, SwapScreenAction
from .client import Client
from .component import spawnLoginScreen, spawnErrorScreen
from .renderer import Renderer


def spawnTerminal(port: str, baudrate: int, flow: bool, wide: bool) -> Terminal:
    print("Attempting to contact VT-100...", end="", file=sys.stderr)
    sys.stderr.flush()

    while True:
        try:
            terminal = SerialTerminal(port, baudrate, flowControl=flow)

            if wide:
                terminal.set132Columns()
            else:
                terminal.set80Columns()

            print("SUCCESS!", file=sys.stderr)
            return terminal
        except TerminalException:
            # Wait for terminal to re-awaken.
            time.sleep(1.0)

            print(".", end="", file=sys.stderr)
            sys.stderr.flush()


def main(
    server: str,
    username: str,
    password: str,
    port: str,
    baudrate: int,
    flow: bool,
    wide: bool,
) -> int:
    # First, attempt to talk to the server.
    client = Client(server)

    exiting = False
    while not exiting:
        # First, attempt to talk to the terminal, and get the current page rendering.
        terminal = spawnTerminal(port, baudrate, flow, wide)
        renderer = Renderer(terminal, client)
        if client.valid:
            spawnLoginScreen(
                renderer, server=server, username=username, password=password
            )
        else:
            spawnErrorScreen(
                renderer,
                error=f"Cannot connect to server {server}.",
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
                        print("Got request to end session!", file=sys.stderr)
                        exiting = True
                    elif isinstance(action, SwapScreenAction):
                        action.swap(renderer, **action.params)
                    elif isinstance(action, BackAction):
                        renderer.pop()

        except TerminalException:
            # Terminal went away mid-transaction.
            print("Lost terminal, will attempt a reconnect.", file=sys.stderr)

        except KeyboardInterrupt:
            print("Got request to end session!", file=sys.stderr)
            exiting = True

    # Restore the screen before exiting.
    terminal.reset()

    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="VT-100 Mastodon Client")

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
        "--wide",
        action="store_true",
        help="Enable wide mode (132 characters instead of 80 characters)",
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
        main(
            args.server,
            args.username,
            args.password,
            args.port,
            args.baud,
            args.flow,
            args.wide,
        )
    )


if __name__ == "__main__":
    cli()
