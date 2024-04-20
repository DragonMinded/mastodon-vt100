import argparse
import emoji
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


class BackAction(Action):
    pass


class SwapScreenAction(Action):
    def __init__(
        self, swap: Callable[["Renderer"], None], **params: Dict[str, Any]
    ) -> None:
        self.swap = swap
        self.params = params or {}


class Component:
    def __init__(self, renderer: "Renderer", top: int, bottom: int) -> None:
        self.renderer = renderer
        self.terminal = renderer.terminal
        self.client = renderer.client
        self.top = top
        self.bottom = bottom
        self.rows = (bottom - top) + 1

    @property
    def properties(self) -> Dict[str, Any]:
        return self.renderer.properties

    def draw(self) -> None:
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


def account(name: str, username: str, width: int) -> Tuple[str, Sequence[ControlCodes]]:
    name = sanitize(name)
    rest = f" @{sanitize(username)}"
    leftover = width - len(rest)
    if len(name) > leftover:
        name = name[: (leftover - 3)] + "\u2022\u2022\u2022"

    return highlight(f"<b>{name}</b>{rest}")


def boost(name: str, username: str, width: int) -> Tuple[str, Sequence[ControlCodes]]:
    name = sanitize(name)
    rest = f" (@{sanitize(username)}) boosted"
    leftover = width - len(rest)
    if len(name) > leftover:
        name = name[: (leftover - 3)] + "\u2022\u2022\u2022"

    return highlight(f"{name}{rest}")


class TimelinePost:
    def __init__(self, renderer: "Renderer", data: Dict[str, Any]) -> None:
        self.renderer = renderer
        self.data = data

        reblog = self.data["reblog"]
        if reblog:
            # First, start with the name of the reblogger.
            name = emoji.demojize(striplow(self.data["account"]["display_name"]))
            username = emoji.demojize(striplow(self.data["account"]["acct"]))
            boostline = boost(name, username, renderer.columns - 2)

            # Now, grab the original name.
            name = emoji.demojize(striplow(reblog["account"]["display_name"]))
            username = emoji.demojize(striplow(reblog["account"]["acct"]))
            nameline = account(name, username, renderer.columns - 2)

            content = emoji.demojize(striplow(reblog["content"]))
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
            name = emoji.demojize(striplow(self.data["account"]["display_name"]))
            username = emoji.demojize(striplow(self.data["account"]["acct"]))
            nameline = account(name, username, renderer.columns - 2)

            content = emoji.demojize(striplow(self.data["content"]))
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

        self.height = len(self.lines)

    def __format_attachments(
        self, attachments: List[Dict[str, Any]]
    ) -> List[Tuple[str, List[ControlCodes]]]:
        attachmentLines = []
        for attachment in attachments:
            alt = striplow(
                emoji.demojize(attachment["description"] or "no description"),
                allow_safe=True,
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

    def draw(self, top: int, bottom: int, offset: int, postno: Optional[int]) -> None:
        # Maybe there's a better way to do this? Maybe display() should take substitutions?
        if postno is not None:
            replace = f"\u2524{postno}\u251c"
        else:
            replace = "\u2500\u2500\u2500"
        replaced, codes = self.lines[0]
        replaced = replaced[:1] + replace + replaced[4:]
        self.lines[0] = (replaced, codes)

        bounds = BoundingRectangle(
            top=top, bottom=bottom + 1, left=1, right=self.renderer.columns + 1
        )
        display(self.renderer.terminal, self.lines[offset:], bounds)


class TimelineComponent(Component):
    def __init__(
        self,
        renderer: "Renderer",
        top: int,
        bottom: int,
        *,
        timeline: Timeline = Timeline.HOME,
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Save params we care about.
        self.timeline = timeline

        # First, fetch the timeline.
        self.offset = 0
        self.statuses = self.client.fetchTimeline(self.timeline)
        self.renderer.status("Timeline fetched, drawing...")

        # Now, format each post into it's own component.
        self.posts = [TimelinePost(self.renderer, status) for status in self.statuses]

        # Keep track of the top of each post, and it's post number, so we can
        # render deep-dive numbers.
        self.positions: Dict[int, int] = self._postIndexes()

    def draw(self) -> None:
        self.__draw()
        self.renderer.status("")

    def __draw(self) -> Optional[Tuple[int, int]]:
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

            minpost = self.positions[min(self.positions.keys())]
            postno = self.positions.get(top)
            post.draw(
                top, bottom, 0, postno - minpost + 1 if postno is not None else None
            )
            pos += post.height

        pos += self.top
        topMissed = pos
        amountMissed = 0
        while pos <= self.bottom:
            self.renderer.terminal.moveCursor(pos, 1)
            self.renderer.terminal.sendCommand(Terminal.CLEAR_LINE)
            pos += 1
            amountMissed += 1

        self.renderer.terminal.moveCursor(self.bottom, self.renderer.terminal.columns)

        if amountMissed > 0:
            return (topMissed, topMissed + (amountMissed - 1))
        else:
            return None

    def _drawOneLine(self, line: int) -> bool:
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

            minpost = self.positions[min(self.positions.keys())]
            postno = self.positions.get(pos + self.top)
            post.draw(
                line, line, offset, postno - minpost + 1 if postno is not None else None
            )
            return True

        self.renderer.terminal.moveCursor(line, 1)
        self.renderer.terminal.sendCommand(Terminal.CLEAR_LINE)
        return False

    def _getPostForLine(self, line: int) -> float:
        pos = -self.offset
        viewHeight = (self.bottom - self.top) + 1

        for cnt, post in enumerate(self.posts):
            if pos >= viewHeight:
                # Too low below the viewport.
                break
            if pos + post.height <= 0:
                # Too high above the viewport.
                pos += post.height
                continue

            top = pos + self.top
            bottom = top + post.height

            if line >= top and line <= bottom:
                start = line - top
                return float(cnt) + (start / (bottom - top))

            pos += post.height

        return 0

    def _postIndexes(self) -> Dict[int, int]:
        ret: Dict[int, int] = {}

        pos = -self.offset

        # We don't break here, so that we can have an easier time telling if
        # something's changed when calling this, by making sure that a post which
        # comes into or goes out of visibility which doesn't change the ordering
        # doesn't cause a redraw.
        for cnt, post in enumerate(self.posts):
            if pos + post.height <= 0:
                # Too high above the viewport.
                pos += post.height
                continue

            top = pos + self.top
            ret[top] = cnt
            pos += post.height

        return ret

    def _getLineForPost(self, postNumber: int) -> Optional[int]:
        pos = 0

        for cnt, post in enumerate(self.posts):
            if cnt == postNumber:
                return pos + self.top

            pos += post.height

        return None

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        infiniteScrollFetch = False
        infiniteScrollRedraw: List[int] = []
        handled = False

        if inputVal == Terminal.UP:
            # Scroll up one line.
            if self.offset > 0:
                self.offset -= 1

                newPositions = self._postIndexes()
                postNumberRedraw = list(self.positions.values()) != list(
                    newPositions.values()
                )
                self.positions = newPositions

                self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                self.terminal.setScrollRegion(self.top, self.bottom)
                self.terminal.moveCursor(self.top, 1)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)

                # Redraw post numbers if necessary.
                if postNumberRedraw:
                    for line in self.positions.keys():
                        if line <= self.top:
                            continue
                        if line > self.bottom:
                            continue
                        self._drawOneLine(line)

                self._drawOneLine(self.top)
                self.terminal.clearScrollRegion()
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

            handled = True

        elif inputVal == Terminal.DOWN:
            # Scroll down one line.
            if self.offset < 0xFFFFFFFF:
                self.offset += 1

                newPositions = self._postIndexes()
                postNumberRedraw = list(self.positions.values()) != list(
                    newPositions.values()
                )
                self.positions = newPositions

                self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                self.terminal.setScrollRegion(self.top, self.bottom)
                self.terminal.moveCursor(self.bottom, 1)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_DOWN)

                # Redraw post numbers if necessary.
                if postNumberRedraw:
                    for line in self.positions.keys():
                        if line < self.top:
                            continue
                        if line >= self.bottom:
                            continue
                        self._drawOneLine(line)

                if not self._drawOneLine(self.bottom):
                    # The line draw didn't do anything, so we need to fetch more
                    # data after we finish drawing.
                    infiniteScrollFetch = True
                    infiniteScrollRedraw.append(self.bottom)
                self.terminal.clearScrollRegion()
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

            handled = True

        elif inputVal == b"q":
            # Log back out.
            self.renderer.status("Logged out.")
            return SwapScreenAction(
                spawnLoginScreen,
                server=self.properties["server"],
                username=self.properties["username"],
            )

        elif inputVal == b"t":
            # Move to top of page.
            if self.offset > 0:
                if self.offset < (self.bottom - self.top) + 1:
                    # We can scroll to save render time.
                    drawAmount = self.offset
                    self.offset = 0

                    newPositions = self._postIndexes()
                    postNumberRedraw = list(self.positions.values()) != list(
                        newPositions.values()
                    )
                    self.positions = newPositions

                    self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                    self.terminal.setScrollRegion(self.top, self.bottom)
                    self.terminal.moveCursor(self.top, 1)
                    for _ in range(drawAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)

                    # Redraw post numbers if necessary.
                    if postNumberRedraw:
                        skippables = {x for x in range(self.top, self.top + drawAmount)}
                        for line in self.positions.keys():
                            if line < self.top:
                                continue
                            if line > self.bottom:
                                continue
                            if line in skippables:
                                continue
                            self._drawOneLine(line)

                    for line in range(drawAmount):
                        self._drawOneLine(self.top + line)
                    self.terminal.clearScrollRegion()
                    self.terminal.sendCommand(Terminal.RESTORE_CURSOR)
                else:
                    # We must redraw the whole screen.
                    self.offset = 0
                    self.positions = self._postIndexes()
                    self.__draw()

            handled = True

        elif inputVal == b"r":
            # Refresh timeline action.
            self.renderer.status("Refetching timeline...")

            self.offset = 0
            self.statuses = self.client.fetchTimeline(self.timeline)
            self.renderer.status("Timeline fetched, drawing...")

            # Now, format each post into it's own component.
            self.posts = [
                TimelinePost(self.renderer, status) for status in self.statuses
            ]
            self.positions = self._postIndexes()

            # Now, draw them.
            self.__draw()
            self.renderer.status("")

            return NullAction()

        elif inputVal == b"p":
            # Move to previous post.
            postAndOffset = self._getPostForLine(self.top)
            whichPost = int(postAndOffset)
            if postAndOffset - whichPost == 0.0:
                # We're on the top line of the current post, grab the previous.
                whichPost -= 1
            if whichPost < 0:
                whichPost = 0

            # Figure out how much we have to move to get there.
            newOffset = self._getLineForPost(whichPost)
            if newOffset is not None:
                moveAmount = self.offset - (newOffset - self.top)
            else:
                moveAmount = 0

            if moveAmount > 0:
                self.offset -= moveAmount

                newPositions = self._postIndexes()
                postNumberRedraw = list(self.positions.values()) != list(
                    newPositions.values()
                )
                self.positions = newPositions

                if moveAmount <= (self.bottom - self.top):
                    # We can scroll to save render time.
                    self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                    self.terminal.setScrollRegion(self.top, self.bottom)
                    self.terminal.moveCursor(self.top, 1)
                    for _ in range(moveAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)

                    # Redraw post numbers if necessary.
                    if postNumberRedraw:
                        skippables = {x for x in range(self.top, self.top + moveAmount)}
                        for line in self.positions.keys():
                            if line < self.top:
                                continue
                            if line > self.bottom:
                                continue
                            if line in skippables:
                                continue
                            self._drawOneLine(line)

                    for line in range(moveAmount):
                        self._drawOneLine(self.top + line)
                    self.terminal.clearScrollRegion()
                    self.terminal.sendCommand(Terminal.RESTORE_CURSOR)
                else:
                    # We must redraw the whole screen.
                    self.__draw()

            handled = True

        elif inputVal == b"n":
            # Move to next post.
            postAndOffset = self._getPostForLine(self.top)
            whichPost = int(postAndOffset) + 1

            if whichPost == len(self.posts) and whichPost > 0:
                # Possibly scrolling to the next entry that hasn't been fetched.
                newOffset = self._getLineForPost(whichPost - 1)
                if newOffset is None:
                    raise Exception(
                        "Logic error, should always be able to get a line for an existing post."
                    )
                newOffset += self.posts[whichPost - 1].height
            else:
                # Figure out how much we have to move to get there.
                newOffset = self._getLineForPost(whichPost)

            if newOffset is not None:
                moveAmount = (newOffset - self.top) - self.offset
            else:
                moveAmount = 0

            if moveAmount > 0:
                self.offset += moveAmount

                newPositions = self._postIndexes()
                postNumberRedraw = list(self.positions.values()) != list(
                    newPositions.values()
                )
                self.positions = newPositions

                if moveAmount <= (self.bottom - self.top):
                    # We can scroll to save render time.
                    self.terminal.sendCommand(Terminal.SAVE_CURSOR)
                    self.terminal.setScrollRegion(self.top, self.bottom)
                    self.terminal.moveCursor(self.bottom, 1)
                    for _ in range(moveAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_DOWN)

                    # Redraw post numbers if necessary.
                    if postNumberRedraw:
                        skippables = {
                            x
                            for x in range(
                                self.bottom - (moveAmount - 1), self.bottom + 1
                            )
                        }
                        for line in self.positions.keys():
                            if line < self.top:
                                continue
                            if line > self.bottom:
                                continue
                            if line in skippables:
                                continue
                            self._drawOneLine(line)

                    for line in range(moveAmount):
                        actualLine = (self.bottom - (moveAmount - 1)) + line
                        if not self._drawOneLine(actualLine):
                            # The line draw didn't do anything, so we need to fetch more
                            # data after we finish drawing.
                            infiniteScrollFetch = True
                            infiniteScrollRedraw.append(actualLine)
                    self.terminal.clearScrollRegion()
                    self.terminal.sendCommand(Terminal.RESTORE_CURSOR)
                else:
                    # We must redraw the whole screen.
                    possibleLineList = self.__draw()
                    if possibleLineList is not None:
                        start, end = possibleLineList
                        for line in range(start, end + 1):
                            infiniteScrollRedraw.append(line)
                        infiniteScrollFetch = True

            handled = True

        if not handled:
            return None

        # Figure out if we should load the next bit of timeline.
        if infiniteScrollFetch:
            self.renderer.status("Fetching more posts...")

            newStatuses = self.client.fetchTimeline(
                self.timeline, since=self.statuses[-1]
            )

            self.renderer.status("Additional posts fetched, drawing...")

            # Now, format each post into it's own component.
            newPosts = [TimelinePost(self.renderer, status) for status in newStatuses]

            self.statuses += newStatuses
            self.posts += newPosts

            # We don't care about whether this changed the order, because it can't.
            # It can only ever add onto the order.
            self.positions = self._postIndexes()

            # Now, draw them.
            for line in infiniteScrollRedraw:
                self._drawOneLine(line)
            self.renderer.status("")

        return NullAction()


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
            return [highlight("<r>" + pad(obfuscate(self.text), self.length) + "</r>")]
        else:
            return [highlight("<r>" + pad(self.text, self.length) + "</r>")]

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

            return NullAction()
        elif inputVal == Terminal.RIGHT:
            if self.cursor < len(self.text):
                self.cursor += 1
                self.renderer.terminal.moveCursor(row, column + self.cursor)

            return NullAction()
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
        self.properties["server"] = server
        self.username = OneLineInputBox(renderer, username, 36)
        self.password = OneLineInputBox(renderer, password, 36, obfuscate=True)

        # Set up which component we're on.
        self.left = (self.renderer.terminal.columns // 2) - 20
        self.right = self.renderer.terminal.columns - self.left
        self.component = 0 if len(username) == 0 else (1 if len(password) == 0 else 2)

    def __login(self) -> bool:
        # Attempt to log in.
        try:
            self.client.login(self.username.text, self.password.text)
            return True
        except BadLoginError:
            return False

    def __moveCursor(self) -> None:
        if self.component == 0:
            self.terminal.moveCursor(
                (self.top - 1) + 7, self.left + 2 + self.username.cursor
            )
        elif self.component == 1:
            self.terminal.moveCursor(
                (self.top - 1) + 10, self.left + 2 + self.password.cursor
            )
        elif self.component == 2:
            self.terminal.moveCursor((self.top - 1) + 13, self.left + 3)
        elif self.component == 3:
            self.terminal.moveCursor((self.top - 1) + 13, self.left + 33)

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
            top=(self.top - 1) + 13,
            bottom=(self.top - 1) + 14,
            left=self.left + 1,
            right=self.right + 1,
        )
        display(self.terminal, lines, bounds)

        # Now, put the cursor back.
        self.__moveCursor()

    def draw(self) -> None:
        # First, clear the screen and draw our logo.
        for row in range(self.top, self.bottom + 1):
            self.terminal.moveCursor(row, 1)
            self.terminal.sendCommand(Terminal.CLEAR_LINE)
        self.terminal.moveCursor((self.top - 1) + 3, (self.left // 2) + 1)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_TOP)
        self.terminal.sendText("Mastodon for VT-100")
        self.terminal.moveCursor((self.top - 1) + 4, (self.left // 2) + 1)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_BOTTOM)
        self.terminal.sendText("Mastodon for VT-100")

        lines = self.__summonBox()
        bounds = BoundingRectangle(
            top=(self.top - 1) + 5,
            bottom=(self.top - 1) + 16,
            left=self.left + 1,
            right=self.right + 1,
        )
        display(self.terminal, lines, bounds)

        # Finally, display the status.
        self.renderer.status(
            f"Please enter your credentials for {self.properties['server']}."
        )

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
                        f"Please enter your credentials for {self.properties['server']}."
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
                    f"Please enter your credentials for {self.properties['server']}."
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
                    # Preserve the username so all scenes can access it.
                    self.properties["username"] = self.username.text

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
                return self.username.processInput(
                    inputVal, (self.top - 1) + 7, self.left + 2
                )
            elif self.component == 1:
                return self.password.processInput(
                    inputVal, (self.top - 1) + 10, self.left + 2
                )

        return None


class ErrorComponent(Component):
    def __init__(
        self,
        renderer: "Renderer",
        top: int,
        bottom: int,
        *,
        error: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Set up for what input we're handling.
        self.error = error
        self.left = (self.renderer.terminal.columns // 2) - 20
        self.right = self.renderer.terminal.columns - self.left

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, create the "quit" button.
        quit = [
            boxtop(6),
            boxmiddle(highlight("<b>quit</b>"), 6),
            boxbottom(6),
        ]

        # Now, create the "middle bit" between the buttons.
        middle = highlight(pad("", 36 - 6))

        text, codes = highlight(self.error)
        textbits = wordwrap(text, codes, 36)

        # Now, create the error box itself.
        lines = [
            boxtop(38),
            *[boxmiddle(bit, 38) for bit in textbits],
            boxmiddle(highlight(""), 38),
            *[boxmiddle(join([middle, quit[x]]), 38) for x in range(len(quit))],
            boxbottom(38),
        ]

        return lines

    def draw(self) -> None:
        # First, clear the screen and draw our logo.
        for row in range(self.top, self.bottom + 1):
            self.terminal.moveCursor(row, 1)
            self.terminal.sendCommand(Terminal.CLEAR_LINE)
        self.terminal.moveCursor((self.top - 1) + 3, (self.left // 2) + 1)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_TOP)
        self.terminal.sendText("Mastodon for VT-100")
        self.terminal.moveCursor((self.top - 1) + 4, (self.left // 2) + 1)
        self.terminal.sendCommand(Terminal.DOUBLE_HEIGHT_BOTTOM)
        self.terminal.sendText("Mastodon for VT-100")

        lines = self.__summonBox()
        bounds = BoundingRectangle(
            top=(self.top - 1) + 5,
            bottom=(self.top - 1) + 16,
            left=self.left + 1,
            right=self.right + 1,
        )
        display(self.terminal, lines, bounds)
        self.renderer.status("")

        # Now, put the cursor in the right spot.
        self.terminal.moveCursor((self.top - 1) + 5 + (len(lines) - 3), self.left + 33)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == b"\r":
            # Ignore this.
            return NullAction()
        elif inputVal == b"\n":
            # Client wants out.
            return ExitAction()

        return None


class Renderer:
    def __init__(self, terminal: Terminal, client: Client) -> None:
        # Our managed objects.
        self.terminal = terminal
        self.client = client

        # Our global properties.
        self.properties: Dict[str, Any] = {}

        # Start with no components.
        self.__components: List[Component] = []
        self.__stack: List[List[Component]] = []
        self.__lastStatus: Optional[str] = None
        self.status("")

    def replace(self, components: List[Component]) -> None:
        self.__components = components[:]
        self.__stack = []
        for component in self.__components:
            component.draw()

    def push(self, components: List[Component]) -> None:
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

    def status(self, text: str) -> None:
        if text == self.__lastStatus:
            return

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

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        # First, try handling it with the registered components.
        for component in self.__components:
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
    renderer.replace(
        [
            LoginComponent(
                renderer,
                top=1,
                bottom=renderer.rows,
                server=server,
                username=username,
                password=password,
            )
        ]
    )


def spawnErrorScreen(
    renderer: Renderer,
    *,
    error: str = "Unknown error.",
) -> None:
    renderer.replace(
        [
            ErrorComponent(
                renderer,
                top=1,
                bottom=renderer.rows,
                error=error,
            )
        ]
    )


def spawnTimelineScreen(
    renderer: Renderer, *, timeline: Timeline = Timeline.HOME
) -> None:
    renderer.push(
        [TimelineComponent(renderer, top=1, bottom=renderer.rows, timeline=timeline)]
    )


def spawnTerminal(port: str, baudrate: int, flow: bool, wide: bool) -> Terminal:
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

    if wide:
        terminal.set132Columns()
    else:
        terminal.set80Columns()
    return terminal


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
                        print("Got request to end session!")
                        exiting = True
                    elif isinstance(action, SwapScreenAction):
                        action.swap(renderer, **action.params)
                    elif isinstance(action, BackAction):
                        renderer.pop()

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
