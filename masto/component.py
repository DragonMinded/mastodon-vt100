from vtpy import Terminal

from typing import Dict, List, Optional, Tuple

from .action import (
    Action,
    NullAction,
    ExitAction,
    BackAction,
    SwapScreenAction,
    FOCUS_INPUT,
)
from .client import Timeline, Visibility, BadLoginError, StatusDict
from .clip import BoundingRectangle
from .drawhelpers import (
    boxtop,
    boxmiddle,
    boxbottom,
    join,
    account,
)
from .renderer import Renderer, SystemProperties
from .subcomponent import (
    TimelinePost,
    FocusWrapper,
    Button,
    HorizontalSelect,
    OneLineInputBox,
    MultiLineInputBox,
)
from .text import ControlCodes, display, html, highlight, wordwrap, pad


class Component:
    def __init__(self, renderer: Renderer, top: int, bottom: int) -> None:
        self.renderer = renderer
        self.terminal = renderer.terminal
        self.client = renderer.client
        self.top = top
        self.bottom = bottom
        self.rows = (bottom - top) + 1

    @property
    def properties(self) -> SystemProperties:
        return self.renderer.properties

    def draw(self) -> None:
        pass

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        return None


class TimelineTabsComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        timeline: Timeline = Timeline.HOME,
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Start with the specified timeline.
        self.timelines: Dict[Timeline, TimelineComponent] = {
            timeline: TimelineComponent(renderer, top + 1, bottom, timeline=timeline),
        }
        self.timeline = timeline
        self.choices: Dict[Timeline, str] = {
            Timeline.HOME: "[H]ome",
            Timeline.LOCAL: "[L]ocal",
            Timeline.PUBLIC: "[G]lobal",
        }

    def draw(self) -> None:
        # First, draw our tabs.
        tabtext = ""
        for choice, text in self.choices.items():
            if choice == self.timeline:
                tabtext += f"<b><r> {text} </r></b> "
            else:
                tabtext += f"<r> {text} </r> "

        tabbits = highlight(tabtext)

        # Clear the line, and then display the text.
        self.renderer.terminal.moveCursor(self.top, len(tabbits[0]) + 1)
        self.renderer.terminal.sendCommand(Terminal.CLEAR_TO_END_OF_LINE)
        bounds = BoundingRectangle(
            top=self.top,
            bottom=self.top + 1,
            left=1,
            right=self.renderer.columns + 1
        )
        display(self.renderer.terminal, [tabbits], bounds)

        # Now, draw the timeline itself.
        self.timelines[self.timeline].draw()

    def __get_help(self) -> str:
        return "".join(
            [
                "<u>Timeline Selection</u><br />",
                "<p><b>h</b> view your home timeline</p>",
                "<p><b>l</b> view your local instance timeline</p>",
                "<p><b>g</b> view the global timeline</p>",
                "<u>Navigation</u><br />",
                "<p><b>up</b> and <b>down</b> keys scroll the timeline up or down one single line.</p>",
                "<p><b>n</b> scrolls until the next post is at the top of the screen.</p>",
                "<p><b>p</b> scrolls until the previous post is at the top of the screen.</p>",
                "<p><b>t</b> scrolls to the top of the timeline.</p>",
                "<u>Actions</u><br />",
                "<p><b>r</b> refreshes the timeline, scrolling to the top of the refreshed content.</p>",
                "<p><b>c</b> opens up the composer to write a new post.</p>",
                "<p><b>q</b> quits to the login screen.</p>",
            ]
        )

    @property
    def drawn(self) -> bool:
        return self.timelines[self.timeline].drawn

    @drawn.setter
    def drawn(self, newval: bool) -> None:
        self.timelines[self.timeline].drawn = newval

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        # First, handle our own input.
        if inputVal == b"?":
            # Display hotkeys action.
            self.drawn = False
            return SwapScreenAction(
                spawnHTMLScreen, content=self.__get_help(), exitMessage="Drawing..."
            )

        if inputVal in {b"h", b"l", b"g"}:
            # Move to tab.
            timeline = {
                b"h": Timeline.HOME,
                b"l": Timeline.LOCAL,
                b"g": Timeline.PUBLIC,
            }[inputVal]

            if self.timeline != timeline:
                # Switch to this timeline.
                if timeline not in self.timelines:
                    self.renderer.status("Fetching timeline...")
                    self.timelines[timeline] = TimelineComponent(self.renderer, self.top + 1, self.bottom, timeline=timeline)

                self.timeline = timeline
                self.draw()

            return NullAction()

        # Now, handle input for the tab we're on.
        return self.timelines[self.timeline].processInput(inputVal)


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
        self.posts = [self.__get_post(status) for status in self.statuses]

        # Keep track of the top of each post, and it's post number, so we can
        # render deep-dive numbers.
        self.positions: Dict[int, int] = self._postIndexes()
        self.drawn = False

    def __get_post(self, status: StatusDict) -> TimelinePost:
        post = TimelinePost(self.renderer, status)
        if self.properties["prefs"].get('reading:expand:spoilers', False):
            # Auto-expand any spoilered text.
            post.toggle_spoiler()
        return post

    def draw(self) -> None:
        self.__draw()
        if not self.drawn:
            self.drawn = True
            if self.properties.get('last_post'):
                self.renderer.status("New status posted! Press '?' for help.")
            else:
                self.renderer.status("Press '?' for help.")

    def __draw(self) -> Optional[Tuple[int, int]]:
        pos = -self.offset
        viewHeight = (self.bottom - self.top) + 1

        # It seems that the cursor can get out of sync in a few rare cases. Fix that
        # here by just moving to the top. If we don't, the screen ends up rendered
        # correctly anyway, but drawn from the bottom up instead of top down. VT-100
        # is fun to code for!
        self.renderer.terminal.moveCursor(self.top, 1)

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
            offset = 0
            if top < self.top:
                offset = self.top - top
                top = self.top

            minpost = self.positions[min(self.positions.keys())]
            postno = self.positions.get(top)
            post.draw(
                top, bottom, offset, postno - minpost + 1 if postno is not None else None
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
                # TODO: might be buggy
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
                self.terminal.moveCursor(self.top, 1)
                self.terminal.setScrollRegion(self.top, self.bottom)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)
                self.terminal.clearScrollRegion()

                # Redraw post numbers if necessary.
                if postNumberRedraw:
                    for line in self.positions.keys():
                        if line <= self.top:
                            continue
                        if line > self.bottom:
                            continue
                        self._drawOneLine(line)

                self._drawOneLine(self.top)
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
                self.terminal.moveCursor((self.bottom - self.top) + 1, 1)
                self.terminal.sendCommand(Terminal.MOVE_CURSOR_DOWN)
                self.terminal.clearScrollRegion()

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
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

            handled = True

        elif inputVal == b"q":
            # Log back out.
            self.properties['last_post'] = None
            self.renderer.status("Logged out.")
            return SwapScreenAction(
                spawnLoginScreen,
                server=self.properties["server"],
                username=self.properties["username"],
            )

        elif inputVal in {b"!", b"@", b"#", b"$", b"%", b"^", b"&", b"*", b"(", b")"}:
            postNo = {
                b"!": 0,
                b"@": 1,
                b"#": 2,
                b"$": 3,
                b"%": 4,
                b"^": 5,
                b"&": 6,
                b"*": 7,
                b"(": 8,
                b")": 9,
            }[inputVal]

            minpost = self.positions[min(self.positions.keys())]
            for off, post in self.positions.items():
                if post - minpost == postNo:
                    # This is the right post.
                    if self.posts[post].toggle_spoiler():
                        # This needs redrawing.
                        for line in range(off, off + self.posts[post].height):
                            if line < self.top:
                                continue
                            if line > self.bottom:
                                continue
                            self._drawOneLine(line)

                    break

            return NullAction()

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
                    self.terminal.moveCursor(self.top, 1)
                    self.terminal.setScrollRegion(self.top, self.bottom)
                    for _ in range(drawAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)
                    self.terminal.clearScrollRegion()

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
                    self.terminal.sendCommand(Terminal.RESTORE_CURSOR)
                else:
                    # We must redraw the whole screen.
                    self.offset = 0
                    self.positions = self._postIndexes()
                    self.__draw()

            handled = True

        elif inputVal == b"r":
            # Refresh timeline action.
            self.properties['last_post'] = None
            self.renderer.status("Refetching timeline...")

            self.offset = 0
            self.statuses = self.client.fetchTimeline(self.timeline)
            self.renderer.status("Timeline fetched, drawing...")

            # Now, format each post into it's own component.
            self.posts = [self.__get_post(status) for status in self.statuses]
            self.positions = self._postIndexes()

            # Now, draw them.
            self.__draw()
            self.renderer.status("Press '?' for help.")

            return NullAction()

        elif inputVal == b"c":
            # Post a new post action.
            self.drawn = False
            self.properties['last_post'] = None
            return SwapScreenAction(spawnPostScreen, exitMessage="Drawing...")

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
                    self.terminal.moveCursor(self.top, 1)
                    self.terminal.setScrollRegion(self.top, self.bottom)
                    for _ in range(moveAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_UP)
                    self.terminal.clearScrollRegion()

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
                    self.terminal.moveCursor((self.bottom - self.top) + 1, 1)
                    for _ in range(moveAmount):
                        self.terminal.sendCommand(Terminal.MOVE_CURSOR_DOWN)
                    self.terminal.clearScrollRegion()

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
            self.properties['last_post'] = None
            self.renderer.status("Fetching more posts...")

            newStatuses = self.client.fetchTimeline(
                self.timeline, since=self.statuses[-1]
            )

            self.renderer.status("Additional posts fetched, drawing...")

            # Now, format each post into it's own component.
            newPosts = [self.__get_post(status) for status in newStatuses]

            self.statuses += newStatuses
            self.posts += newPosts

            # We don't care about whether this changed the order, because it can't.
            # It can only ever add onto the order.
            self.positions = self._postIndexes()

            # Now, draw them.
            for line in infiniteScrollRedraw:
                self._drawOneLine(line)
            self.renderer.status("Press '?' for help.")

        return NullAction()


class NewPostComponent(Component):
    def __init__(self, renderer: Renderer, top: int, bottom: int, exitMessage: str = "") -> None:
        super().__init__(renderer, top, bottom)

        self.exitMessage = exitMessage

        # Figure out their default posting preference.
        server_pref = self.properties["prefs"].get('posting:default:visibility', 'public')
        default_visibility: Optional[str] = {
            'public': "public",
            'unlisted': "quiet public",
            'private': "followers",
        }.get(server_pref)

        self.component = 0

        self.postBody = MultiLineInputBox(
            renderer, "", self.top + 2, 2, self.renderer.columns - 2, 10
        )
        self.cw = OneLineInputBox(
            renderer, "", self.top + 13, 2, self.renderer.columns - 2
        )
        self.visibility = HorizontalSelect(
            renderer,
            ["public", "quiet public", "followers", "specific accounts"],
            self.top + 14,
            19,
            25,
            selected=default_visibility,
        )
        self.post = Button(renderer, "Post", self.top + 17, 2)
        self.discard = Button(renderer, "Discard", self.top + 17, 9)
        self.focusWrapper = FocusWrapper(
            [self.postBody, self.cw, self.visibility, self.post, self.discard], 0
        )

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        lines: List[Tuple[str, List[ControlCodes]]] = []

        # First, create the top "Posting as" section.
        lines.append(
            join(
                [
                    highlight("Posting as "),
                    account(
                        self.properties["account"]["display_name"],
                        self.properties["account"]["username"],
                        self.renderer.columns - 13,
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
        # Display help for navigating.
        self.renderer.status("Use tab to move between inputs.")

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
                status = self.postBody.text
                if self.cw.text:
                    cw = self.cw.text
                else:
                    cw = None

                for text, visEnum in [
                    ("public", Visibility.PUBLIC),
                    ("quiet public", Visibility.UNLISTED),
                    ("followers", Visibility.PRIVATE),
                    ("specific accounts", Visibility.DIRECT),
                ]:
                    if text == self.visibility.selected:
                        visibility = visEnum
                        break
                else:
                    raise Exception("Logic error, couldn't map visibility!")

                self.properties['last_post'] = self.client.createPost(status, visibility, cw=cw)
                self.renderer.status("New status posted! Drawing...")

                # Go back now, once post was successfully posted.
                return BackAction()
            elif self.focusWrapper.component == 4:
                # Client wants to discard their post.
                if self.exitMessage:
                    self.renderer.status(self.exitMessage)
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
        self.username = OneLineInputBox(
            renderer, username, (self.top - 1) + 7, self.left + 2, 36
        )
        self.password = OneLineInputBox(
            renderer, password, (self.top - 1) + 10, self.left + 2, 36, obfuscate=True
        )
        self.login = Button(
            renderer,
            "login",
            (self.top - 1) + 12,
            self.left + 2,
            focused=component == 2,
        )
        self.quit = Button(
            renderer,
            "quit",
            (self.top - 1) + 12,
            self.left + 32,
            focused=component == 3,
        )

        self.focusWrapper = FocusWrapper(
            [self.username, self.password, self.login, self.quit], component
        )

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
                    self.properties["prefs"] = self.client.getPreferences()

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
        self.quit = Button(
            renderer,
            "quit",
            self.top + 6 + len(self.textbits),
            self.left + 32,
            focused=True,
        )

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


class HTMLComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        content: str = "",
        exitMessage: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)

        self.exitMessage = exitMessage

        content, codes = html(content)
        self.lines = [
            (t, list(c)) for (t, c) in wordwrap(content, codes, self.renderer.columns)
        ]

        # If we ever make this more complex, we'll need to scroll here.
        maxLines = (self.bottom - self.top) + 1
        if len(self.lines) > maxLines:
            self.lines = self.lines[:maxLines]

    def draw(self) -> None:
        # Fill in the lines so we can blank the screen.
        self.renderer.status("Press 'b' to go back to the previous screen.")
        for line in range(self.top, self.bottom + 1):
            self.renderer.terminal.moveCursor(line, 1)
            self.renderer.terminal.sendCommand(Terminal.CLEAR_LINE)

        # Just draw the HTML.
        bounds = BoundingRectangle(
            top=self.top,
            bottom=self.top + len(self.lines),
            left=1,
            right=self.renderer.columns + 1,
        )
        display(self.terminal, self.lines, bounds)

        # Move the cursor somewhere arbitrary.
        self.renderer.terminal.moveCursor(self.bottom, self.renderer.columns)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == b"b":
            # Go back to the previous page.
            if self.exitMessage:
                self.renderer.status(self.exitMessage)
            return BackAction()

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
    renderer.push([TimelineTabsComponent(renderer, top=1, bottom=renderer.rows, timeline=timeline)])


def spawnPostScreen(renderer: Renderer, exitMessage: str = "") -> None:
    renderer.push([NewPostComponent(renderer, top=1, bottom=renderer.rows, exitMessage=exitMessage)])


def spawnHTMLScreen(
    renderer: Renderer, *, content: str = "", exitMessage: str = ""
) -> None:
    renderer.push(
        [
            HTMLComponent(
                renderer,
                top=1,
                bottom=renderer.rows,
                content=content,
                exitMessage=exitMessage,
            )
        ]
    )
