from vtpy import Terminal

from action import Action, NullAction, ExitAction, BackAction, SwapScreenAction, FOCUS_INPUT
from client import Timeline, BadLoginError
from clip import BoundingRectangle
from drawhelpers import (
    boxtop,
    boxmiddle,
    boxbottom,
    join,
    account,
)
from renderer import Renderer
from subcomponent import TimelinePost, FocusWrapper, Button, HorizontalSelect, OneLineInputBox, MultiLineInputBox
from text import ControlCodes, display, highlight, wordwrap, pad

from typing import Any, Dict, List, Optional, Tuple


class Component:
    def __init__(self, renderer: Renderer, top: int, bottom: int) -> None:
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


class TimelineComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
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
            # Post a new post action.
            return SwapScreenAction(spawnPostScreen)

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


class NewPostComponent(Component):
    def __init__(self, renderer: Renderer, top: int, bottom: int) -> None:
        super().__init__(renderer, top, bottom)

        self.component = 0

        self.postBody = MultiLineInputBox(renderer, "", self.top + 2, 2, self.renderer.columns - 2, 10)
        self.cw = OneLineInputBox(renderer, "", self.top + 13, 2, self.renderer.columns - 2)
        self.visibility = HorizontalSelect(renderer, ["public", "quiet public", "followers", "specific accounts"], self.top + 14, 19, 25)
        self.post = Button(renderer, "Post", self.top + 17, 2)
        self.discard = Button(renderer, "Discard", self.top + 17, 9)
        self.focusWrapper = FocusWrapper([self.postBody, self.cw, self.visibility, self.post, self.discard], 0)

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        lines: List[Tuple[str, List[ControlCodes]]] = []

        # First, create the top "Posting as" section.
        lines.append(
            join(
                [
                    highlight("Posting as "),
                    account(
                        self.properties["account"]["display_name"], self.properties["username"], self.renderer.columns - 13
                    ),
                ]
            )
        )

        # Now, add the CW text input.
        lines.extend(self.postBody.lines)
        lines.append(highlight("Optional CW:"))
        lines.append(self.cw.lines[0])

        # Now, add the post visibility selection.
        visibilityLines = self.visibility.lines
        lines.append(join([highlight(" " * 17), visibilityLines[0]]))
        lines.append(join([highlight("Post Visibility: "), visibilityLines[1]]))
        lines.append(join([highlight(" " * 17), visibilityLines[2]]))

        # Now, add the post and discard buttons.
        postLines = self.post.lines
        discardLines = self.discard.lines
        for i in range(3):
            lines.append(join([postLines[i], highlight(" "), discardLines[i]]))

        return [
            boxtop(self.renderer.columns),
            *[boxmiddle(line, self.renderer.columns) for line in lines],
            boxbottom(self.renderer.columns),
        ]

    def draw(self) -> None:
        # First, draw the top bits.
        lines = self.__summonBox()
        bounds = BoundingRectangle(
            top=self.top,
            bottom=self.top + len(lines),
            left=1,
            right=self.renderer.columns + 1,
        )
        display(self.terminal, lines, bounds)

        # Now, clear the rest of the display.
        for line in range(self.top + len(lines), self.bottom + 1):
            self.terminal.moveCursor(line, 1)
            self.terminal.sendCommand(Terminal.CLEAR_LINE)

        # Now, put the cursor in the right spot.
        self.focusWrapper.focus()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == Terminal.UP:
            if self.focusWrapper.component == 0:
                # Cursor navigation.
                return self.focusWrapper.processInput(inputVal)
            else:
                # Go to previous component.
                self.focusWrapper.previous()

                return NullAction()
        elif inputVal == Terminal.DOWN:
            if self.focusWrapper.component == 0:
                # Cursor navigation.
                return self.focusWrapper.processInput(inputVal)
            else:
                # Go to next component.
                self.focusWrapper.next()

                return NullAction()

        elif inputVal in {Terminal.LEFT, Terminal.RIGHT}:
            # Pass on to components.
            return self.focusWrapper.processInput(inputVal)

        elif inputVal == b"\t":
            # Go to next component.
            self.focusWrapper.next(wrap=True)

            return NullAction()

        elif inputVal == b"\r":
            # Ignore this.
            return NullAction()

        elif inputVal == b"\n":
            # Client pressed enter.
            if self.focusWrapper.component == 0:
                self.postBody.processInput(inputVal)
            if self.focusWrapper.component in {1, 2}:
                self.focusWrapper.next()
            elif self.focusWrapper.component == 3:
                # Actually attempt to post.
                pass
            elif self.focusWrapper.component == 4:
                # Client wants to discard their post.
                return BackAction()

            return NullAction()
        else:
            return self.focusWrapper.processInput(inputVal)


class LoginComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        server: str = "",
        username: str = "",
        password: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Set up which component we're on.
        self.left = (self.renderer.terminal.columns // 2) - 20
        self.right = self.renderer.terminal.columns - self.left
        component = 0 if len(username) == 0 else (1 if len(password) == 0 else 2)

        # Set up for what input we're handling.
        self.properties["server"] = server
        self.username = OneLineInputBox(renderer, username, (self.top - 1) + 7, self.left + 2, 36)
        self.password = OneLineInputBox(renderer, password, (self.top - 1) + 10, self.left + 2, 36, obfuscate=True)
        self.login = Button(renderer, "login", (self.top - 1) + 12, self.left + 2, focused=component == 2)
        self.quit = Button(renderer, "quit", (self.top - 1) + 12, self.left + 32, focused=component == 3)

        self.focusWrapper = FocusWrapper([self.username, self.password, self.login, self.quit], component)

    def __login(self) -> bool:
        # Attempt to log in.
        try:
            self.client.login(self.username.text, self.password.text)
            return True
        except BadLoginError:
            return False

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, create the "log in" and "quit" buttons.
        login = self.login.lines
        quit = self.quit.lines

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
        self.focusWrapper.focus()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == Terminal.UP:
            # Go to previous component.
            self.focusWrapper.previous()

            # Redraw prompt, in case they typed a bad username and password.
            if self.focusWrapper.component == 1:
                self.renderer.status(
                    f"Please enter your credentials for {self.properties['server']}."
                )

            return NullAction()
        elif inputVal == Terminal.DOWN:
            # Go to next component.
            self.focusWrapper.next()

            return NullAction()
        elif inputVal == b"\r":
            # Ignore this.
            return NullAction()
        elif inputVal == b"\t":
            # Client pressed tab.
            self.focusWrapper.next(wrap=True)

            # Redraw prompt, in case they typed a bad username and password.
            if self.focusWrapper.component == 0:
                self.renderer.status(
                    f"Please enter your credentials for {self.properties['server']}."
                )

            return NullAction()
        elif inputVal == b"\n":
            # Client pressed enter.
            if self.focusWrapper.component in {0, 1}:
                self.focusWrapper.next()
            elif self.focusWrapper.component == 2:
                # Actually attempt to log in.
                if self.__login():
                    # Preserve the username so all scenes can access it.
                    self.properties["username"] = self.username.text

                    # Look up other account info for everyone to use.
                    self.properties["account"] = self.client.getAccountInfo()

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
            elif self.focusWrapper.component == 3:
                # Client wants out.
                return ExitAction()

            return NullAction()
        else:
            return self.focusWrapper.processInput(inputVal)


class ErrorComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        error: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Set up for what input we're handling.
        self.left = (self.renderer.terminal.columns // 2) - 20
        self.right = self.renderer.terminal.columns - self.left

        text, codes = highlight(error)
        self.textbits = wordwrap(text, codes, 36)
        self.quit = Button(renderer, "quit", self.top + 6 + len(self.textbits), self.left + 32, focused=True)

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, create the "quit" button.
        quit = self.quit.lines

        # Now, create the "middle bit" between the buttons.
        middle = highlight(pad("", 36 - 6))

        # Now, create the error box itself.
        lines = [
            boxtop(38),
            *[boxmiddle(bit, 38) for bit in self.textbits],
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
        self.quit.processInput(FOCUS_INPUT)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == b"\r":
            # Ignore this.
            return NullAction()
        elif inputVal == b"\n":
            # Client wants out.
            return ExitAction()

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


def spawnPostScreen(renderer: Renderer) -> None:
    renderer.push([NewPostComponent(renderer, top=1, bottom=renderer.rows)])
