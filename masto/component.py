import emoji
from vtpy import Terminal

from typing import Callable, Dict, List, Optional, Set, Tuple

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
    PostThreadInfo,
    FocusWrapper,
    Button,
    HorizontalSelect,
    OneLineInputBox,
    MultiLineInputBox,
)
from .text import ControlCodes, display, html, highlight, pad, plain, wordwrap


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
                "<b>h</b> view your home timeline<br />",
                "<b>l</b> view your local instance timeline<br />",
                "<b>g</b> view the global timeline<br />",
                "<br />",
                "<u>Navigation</u><br />",
                "<b>[up]</b> and <b>[down]</b> keys scroll the timeline up or down one single line.<br />",
                "<b>n</b> scrolls until the next post is at the top of the screen.<br />",
                "<b>p</b> scrolls until the previous post is at the top of the screen.<br />",
                "<b>t</b> scrolls to the top of the timeline.<br />",
                "<br />",
                "<u>Actions</u><br />",
                "<b>r</b> refreshes the timeline, scrolling to the top of the refreshed content.<br />",
                "<b>c</b> opens up the composer to write a new post.<br />",
                "<b>v</b> opens up thread view on the last-posted status.<br />",
                "<b>0</b>-<b>9</b> loads thread view for a numbered post, displaying replies.<br />",
                "<b>[shift]</b>+<b>0</b>-<b>9</b> toggles CW'd text for a numbered post.<br />",
                "<b>q</b> quits to the login screen.<br />",
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


class _PostDisplayComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
    ) -> None:
        super().__init__(renderer, top, bottom)

        # First, fetch the timeline.
        self.offset: int = 0
        self.__status_lut: Dict[TimelinePost, StatusDict] = {}
        self.posts: List[TimelinePost] = []
        self.positions: Dict[int, int] = self._postIndexes()

    def _get_post(self, status: StatusDict, threadInfo: Optional[PostThreadInfo] = None) -> TimelinePost:
        post = TimelinePost(self.renderer, status, threadInfo)
        if self.properties["prefs"].get('reading:expand:spoilers', False):
            # Auto-expand any spoilered text.
            post.toggle_spoiler()

        self.__status_lut[post] = status
        return post

    def _get_status_from_post(self, post: TimelinePost) -> StatusDict:
        return self.__status_lut[post]

    def _draw(self) -> Optional[Tuple[int, int]]:
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
        raise NotImplementedError("This isn't meant to be implemented here!")


class TimelineComponent(_PostDisplayComponent):
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
        self.posts = [self._get_post(status) for status in self.statuses]

        # Keep track of the top of each post, and it's post number, so we can
        # render deep-dive numbers.
        self.positions = self._postIndexes()
        self.drawn: bool = False

    def draw(self) -> None:
        self._draw()
        if not self.drawn:
            self.drawn = True
            if self.properties.get('last_post'):
                self.renderer.status("New status posted! Press 'v' to view. Press '?' for help.")
            else:
                self.renderer.status("Press '?' for help.")

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

        elif inputVal == b"v":
            if self.properties.get('last_post'):
                self.renderer.status("Fetching post and replies...")
                return SwapScreenAction(spawnPostAndRepliesScreen, post=self.properties['last_post'])

            return NullAction()

        elif inputVal in {b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8", b"9", b"0"}:
            postNo = {
                b"1": 0,
                b"2": 1,
                b"3": 2,
                b"4": 3,
                b"5": 4,
                b"6": 5,
                b"7": 6,
                b"8": 7,
                b"9": 8,
                b"0": 9,
            }[inputVal]

            minpost = self.positions[min(self.positions.keys())]
            for off, post in self.positions.items():
                if off > self.bottom:
                    break

                if post - minpost == postNo:
                    # This is the right post.
                    status = self.statuses[post]

                    self.renderer.status("Fetching post and replies...")
                    self.properties['last_post'] = None
                    return SwapScreenAction(spawnPostAndRepliesScreen, post=status)

            return NullAction()

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
                if off > self.bottom:
                    break

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
                    self._draw()

            handled = True

        elif inputVal == b"r":
            # Refresh timeline action.
            self.properties['last_post'] = None
            self.renderer.status("Refetching timeline...")

            self.offset = 0
            self.statuses = self.client.fetchTimeline(self.timeline)
            self.renderer.status("Timeline fetched, drawing...")

            # Now, format each post into it's own component.
            self.posts = [self._get_post(status) for status in self.statuses]
            self.positions = self._postIndexes()

            # Now, draw them.
            self._draw()
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
                    self._draw()

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
                    possibleLineList = self._draw()
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
            newPosts = [self._get_post(status) for status in newStatuses]

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


class PostViewComponent(_PostDisplayComponent):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        postId: int = 0,
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Save params we care about.
        self.postId = postId

        # Fetch the post and calculate random stuff about it.
        self._fetchPostFromId()
        self.drawn: bool = False

    def __get_help(self) -> str:
        return "".join(
            [
                "<u>Navigation</u><br />",
                "<b>[up]</b> and <b>[down]</b> keys scroll the thread up or down one single line.<br />",
                "<b>n</b> scrolls until the next post is at the top of the screen.<br />",
                "<b>p</b> scrolls until the previous post is at the top of the screen.<br />",
                "<b>t</b> scrolls to the top of the thread.<br />",
                "<br />",
                "<u>Current Post Actions</u><br />",
                "<b>c</b> opens up the composer to write a reply to the current post.<br />",
                "<b>e</b> edits the current post, if it was written by you.<br />",
                "<b>d</b> deletes the current post, if it was written by you.<br />",
                "<b>b</b> boosts or unboosts the current post.<br />",
                "<b>l</b> likes or unlikes the current post.<br />",
                "<b>s</b> saves or unsaves the current post to your bookmarks.<br />",
                "<br />",
                "<u>Thread Actions</u><br />",
                "<b>r</b> refreshes the thread, scrolling to the current post.<br />",
                "<b>0</b>-<b>9</b> loads thread view for a numbered post, displaying replies.<br />",
                "<b>[shift]</b>+<b>0</b>-<b>9</b> toggles CW'd text for a numbered post.<br />",
                "<b>[left]</b> or <b>[backspace]</b> goes back to the previous view.<br />",
                "<b>q</b> quits to the login screen.<br />",
            ]
        )

    def _fetchPostFromId(self, display_status: bool = True) -> None:
        self.post = self.client.fetchPostAndRelated(self.postId)
        if display_status:
            self.renderer.status("Post fetched, drawing...")

        self._formatPost()

    def _formatPost(self) -> None:
        if self.post:
            # Now, format each post into it's own component.
            self.posts = self._get_posts(self.post)
            self.limit = max(0, sum([p.height for p in self.posts]) - ((self.bottom - self.top) + 1))

            # Endeavor to have the current post at the top of the screen.
            self.offset = 0
            for post in self.posts:
                if self._get_status_from_post(post)['id'] == self.postId:
                    break

                self.offset += post.height
            else:
                # Somehow didn't find the highlighted post?
                self.offset = 0

            if self.offset > self.limit:
                self.offset = self.limit

            # Keep track of the top of each post, and it's post number, so we can
            # render deep-dive numbers.
            self.positions = self._postIndexes()
        else:
            self.posts = []
            self.limit = 0
            self.offset = 0
            self.positions = {}

    def _is_single_thread(self, post: StatusDict) -> bool:
        if len(post['replies']) == 0:
            return True
        if len(post['replies']) >= 2:
            return False
        return self._is_single_thread(post['replies'][0])

    def _unwrap_thread(self, post: StatusDict, level: int, siblingLevels: Set[int]) -> List[TimelinePost]:
        if post['replies']:
            return [
                self._get_post(
                    post,
                    PostThreadInfo(
                        level,
                        False,  # highlight
                        True,  # hasDescendants
                        True,  # hasAncestors
                        False,  # hasParent
                        False,  # hasSiblings
                        siblingLevels,
                    ),
                ),
                *self._unwrap_thread(post['replies'][0], level, siblingLevels),
            ]
        else:
            return [
                self._get_post(
                    post,
                    PostThreadInfo(
                        level,
                        False,  # highlight
                        False,  # hasDescendants
                        True,  # hasAncestors
                        False,  # hasParent
                        False,  # hasSiblings
                        siblingLevels,
                    ),
                )
            ]

    def _stack_thread(self, posts: List[StatusDict], level: int, siblingLevels: Set[int]) -> List[TimelinePost]:
        displayables: List[TimelinePost] = []

        last = len(posts) - 1
        for pos, post in enumerate(posts):
            hasSiblings = pos != last
            displayables.append(
                self._get_post(
                    post,
                    PostThreadInfo(
                        level,
                        False,  # highlight
                        bool(post['replies']),  # hasDescendants
                        False,  # hasAncestors
                        True,  # hasParent
                        hasSiblings,  # hasSiblings
                        siblingLevels,
                    ),
                )
            )

            if hasSiblings:
                newLevels = {level, *siblingLevels}
            else:
                newLevels = siblingLevels

            if post['replies']:
                if self._is_single_thread(post):
                    displayables += self._unwrap_thread(post['replies'][0], level, newLevels)
                else:
                    displayables += self._stack_thread(post['replies'], level + 1, newLevels)

        return displayables

    def _get_posts(self, post: StatusDict) -> List[TimelinePost]:
        posts: List[TimelinePost] = []

        # First, handle any ancestors.
        postHasAncestors = False
        postHasDescendants = bool(post['replies'])

        if post['ancestors']:
            postHasAncestors = True
            for ancestor in post['ancestors']:
                posts.append(
                    self._get_post(
                        ancestor,
                        PostThreadInfo(
                            0,
                            False,  # highlight
                            True,  # has descendants.
                            bool(posts),  # has ancestors.
                            False,  # has parent.
                            False,  # has siblings.
                            set(),
                        ),
                    )
                )

        posts.append(
            self._get_post(
                post,
                PostThreadInfo(
                    0,
                    True,  # highlight
                    postHasDescendants,
                    postHasAncestors,
                    False,  # has parent.
                    False,  # has siblings.
                    set(),
                ),
            )
        )

        if post['replies']:
            if self._is_single_thread(post):
                # Easy thing, just unwrap
                posts += self._unwrap_thread(post['replies'][0], 0, set())
            else:
                # Harder thing, display stacked
                posts += self._stack_thread(post['replies'], 1, set())

        return posts

    def draw(self) -> None:
        # If we're redrawing and there is a last post, it means we just replied. So, replace
        # our view with this new one and load it before drawing.
        if self.properties.get('last_post'):
            self.postId = self.properties['last_post']['id']  # type: ignore
            self.properties['last_post'] = None
            self._fetchPostFromId()

        if self.post:
            self._draw()
        else:
            text, codes = highlight("The requested post could not be found. It may have been deleted by the author.")
            textlines = wordwrap(text, codes, self.renderer.columns - 2)

            lines = [
                boxtop(self.renderer.columns),
                *[boxmiddle(line, self.renderer.columns) for line in textlines],
                boxbottom(self.renderer.columns),
            ]

            bounds = BoundingRectangle(
                top=self.top, bottom=self.bottom, left=1, right=self.renderer.columns + 1
            )
            display(self.renderer.terminal, lines, bounds)

            pos = self.top + len(lines)

            while pos <= self.bottom:
                self.renderer.terminal.moveCursor(pos, 1)
                self.renderer.terminal.sendCommand(Terminal.CLEAR_LINE)
                pos += 1

            self.renderer.terminal.moveCursor(self.bottom, self.renderer.terminal.columns)

        if not self.drawn:
            self.drawn = True
            self.renderer.status("Press '?' for help.")

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == b"?":
            # Display hotkeys action.
            self.drawn = False
            return SwapScreenAction(
                spawnHTMLScreen, content=self.__get_help(), exitMessage="Drawing..."
            )

        elif inputVal == Terminal.UP:
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

            return NullAction()

        elif inputVal == Terminal.DOWN:
            # Scroll down one line.
            if self.offset < self.limit:
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

                self._drawOneLine(self.bottom)
                self.terminal.sendCommand(Terminal.RESTORE_CURSOR)

            return NullAction()

        elif inputVal == b"q":
            # Log back out.
            self.renderer.status("Logged out.")
            return SwapScreenAction(
                spawnLoginScreen,
                server=self.properties["server"],
                username=self.properties["username"],
            )

        elif inputVal == b"c":
            # Post a new reply action.
            if self.post:
                self.drawn = False
                self.properties['last_post'] = None
                return SwapScreenAction(spawnPostScreen, replyTo=self.post, exitMessage="Drawing...")

            return NullAction()

        elif inputVal == b"e":
            # Edit current reply action.
            if self.post:
                if not self.post["reblog"] and self.post['account']['id'] == self.properties["account"]["id"]:
                    target = self.post
                elif self.post["reblog"] and self.post['reblog']['account']['id'] == self.properties["account"]["id"]:
                    target = self.post['reblog']
                else:
                    target = None

                if target:
                    self.drawn = False
                    self.properties['last_post'] = None
                    return SwapScreenAction(spawnPostScreen, edit=target, exitMessage="Drawing...")

            return NullAction()

        elif inputVal == b"d":
            # Delete current reply action.
            if self.post:
                if not self.post["reblog"] and self.post['account']['id'] == self.properties["account"]["id"]:
                    target = self.post
                elif self.post["reblog"] and self.post['reblog']['account']['id'] == self.properties["account"]["id"]:
                    target = self.post['reblog']
                else:
                    target = None

                if target:
                    def yes() -> None:
                        self.renderer.status("Deleting post...")
                        self.client.deletePost(target)  # type: ignore
                        self.properties['last_post'] = None
                        self._fetchPostFromId(display_status=False)
                        self.drawn = False

                    def no() -> None:
                        self.renderer.status("Drawing...")
                        self.drawn = False

                    return SwapScreenAction(
                        spawnConfirmationScreen,
                        text="Are you sure you want to delete this post? This action cannot be undone!",
                        yes=yes,
                        no=no,
                    )

            return NullAction()

        elif inputVal == b"b":
            # Boost or unboost current reply action.
            if self.post:
                target = self.post['reblog']
                if not target:
                    target = self.post

                self.properties['last_post'] = None

                if target['reblogged']:
                    # Need to unboost this.
                    self.renderer.status("Unboosting post...")
                    update = self.client.unboostPost(target)
                    self.post['reblogged'] = update['reblogged']
                    self.post['reblogs_count'] = update['reblogs_count']
                    action = "unboosted"
                else:
                    # Need to boost this
                    self.renderer.status("Boosting post...")
                    update = self.client.boostPost(target)

                    reblog = update['reblog']
                    if reblog:
                        self.post['reblogged'] = reblog['reblogged']
                        self.post['reblogs_count'] = reblog['reblogs_count']
                    action = "boosted"

                self._formatPost()
                self.drawn = False
                self.renderer.status(f"Post {action}, drawing...")
                self.draw()

            return NullAction()

        elif inputVal in {b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8", b"9", b"0"}:
            if self.post:
                postNo = {
                    b"1": 0,
                    b"2": 1,
                    b"3": 2,
                    b"4": 3,
                    b"5": 4,
                    b"6": 5,
                    b"7": 6,
                    b"8": 7,
                    b"9": 8,
                    b"0": 9,
                }[inputVal]

                minpost = self.positions[min(self.positions.keys())]
                for off, post in self.positions.items():
                    if off > self.bottom:
                        break

                    if post - minpost == postNo:
                        # This is the right post, go to the same screen as we're on but with
                        # the new post highlighted as the current post.
                        status = self._get_status_from_post(self.posts[post])

                        self.renderer.status("Fetching post and replies...")
                        return SwapScreenAction(spawnPostAndRepliesScreen, post=status)

            return NullAction()

        elif inputVal in {b"!", b"@", b"#", b"$", b"%", b"^", b"&", b"*", b"(", b")"}:
            if self.post:
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
                    if off > self.bottom:
                        break

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
                    self._draw()

            return NullAction()

        elif inputVal in {Terminal.LEFT, Terminal.BACKSPACE}:
            # Go back to timeline view.
            return BackAction()

        elif inputVal == b"r":
            # Refresh post action
            self.renderer.status("Refetching post and replies...")
            self._fetchPostFromId()

            # Now, draw them.
            self._draw()
            self.renderer.status("Press '?' for help.")

            return NullAction()

        elif inputVal == b"p":
            if self.post:
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
                        self._draw()

            return NullAction()

        elif inputVal == b"n":
            if self.post:
                # Move to next post. Unlike normal timeline view, this doesn't allow scrolling "past"
                # the final post, since there's no infinite scroll. Instead, if your next post action
                # would scroll past the final post, we only scroll enough to put that in focus.
                if self.offset < self.limit:
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

                    if self.offset + moveAmount >= self.limit:
                        moveAmount = self.limit - self.offset

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
                                self._drawOneLine(actualLine)
                            self.terminal.sendCommand(Terminal.RESTORE_CURSOR)
                        else:
                            # We must redraw the whole screen.
                            self._draw()

            return NullAction()

        return None


class ComposePostComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        edit: Optional[StatusDict] = None,
        inReplyTo: Optional[StatusDict] = None,
        exitMessage: str = "",
    ) -> None:
        super().__init__(renderer, top, bottom)
        if inReplyTo and edit:
            raise Exception("Logic error, can't edit and reply to a post at once!")

        self.exitMessage = exitMessage
        self.inReplyTo = inReplyTo
        self.edit = edit
        self.verb = "reply" if inReplyTo else ("edit" if edit else "post")

        # Figure out their default posting preference.
        server_pref = self.properties["prefs"].get('posting:default:visibility', 'public')
        if inReplyTo:
            # Reply visibility is copied from the post we reply to.
            postVisibility = inReplyTo['visibility'] or 'public'
            if postVisibility == 'public':
                # In this case, we let the server pref win out.
                postVisibility = server_pref
            elif postVisibility == 'unlisted':
                # In this case, we let the server pref win out unless it was public.
                if server_pref not in {'public'}:
                    postVisibility = server_pref
            elif postVisibility == 'private':
                # In this case, we let the server pref win out unless it was public/unlisted.
                if server_pref not in {'public', 'unlisted'}:
                    postVisibility = server_pref
            elif postVisibility == 'direct':
                # In this case, we're as private as we can get, so server pref is irrelevant.
                pass
        elif edit:
            # Edit visibility is simply preserved.
            postVisibility = edit['visibility'] or 'invalid'
        else:
            # No reply, so post visibility IS the server pref.
            postVisibility = server_pref

        if postVisibility not in {'public', 'unlisted', 'private', 'direct'}:
            raise Exception(f"Logic error, unknown visibility {postVisibility}")

        default_visibility: str = {
            'public': "public",
            'unlisted': "quiet public",
            'private': "followers",
            'direct': "specific accounts",
        }[postVisibility]

        self.component = 0

        # For replies, start with the input box replying to participants.
        if inReplyTo:
            accounts: List[str] = []
            ignored: List[int] = [inReplyTo['account']['id'], self.properties['account']['id']]
            if inReplyTo['account']['id'] != self.properties['account']['id']:
                accounts.append(inReplyTo['account']['acct'])

            for acct in inReplyTo['mentions'] or []:
                if acct['id'] not in ignored:
                    accounts.append(acct['acct'])
                    ignored.append(acct['id'])

            postText = " ".join(f"@{a}" for a in accounts)
            if postText:
                postText += " "
        # For edits, start with the input box as the original status.
        elif edit:
            # The API for masto specifies the content will ALWAYS be in HTML, so we need to
            # strip it. Otherwise we get HTML markings in the edit iteslf.
            postText = emoji.demojize(plain(edit['content']))
        else:
            postText = ""

        self.postBody = MultiLineInputBox(
            renderer, postText, self.top + 2, 2, self.renderer.columns - 2, 10
        )
        self.originalText = postText

        # Match the CW from a reply if it is present.
        if inReplyTo:
            cwText = inReplyTo['spoiler_text'] or ""
        # Match the CW from the edit if it is present.
        elif edit:
            cwText = edit['spoiler_text'] or ""
        else:
            cwText = ""
        self.cw = OneLineInputBox(
            renderer, cwText, self.top + 13, 2, self.renderer.columns - 2
        )

        # Cannot edit visibility when in edit post mode, so we just give one option to the user.
        self.visibility = HorizontalSelect(
            renderer,
            [default_visibility] if edit else ["public", "quiet public", "followers", "specific accounts"],
            self.top + 14,
            15 + len(self.verb),
            25,
            selected=default_visibility,
        )
        self.post = Button(renderer, self.verb.capitalize(), self.top + 17, 2)
        self.discard = Button(renderer, "Discard", self.top + 17, 5 + len(self.verb))
        self.focusWrapper = FocusWrapper(
            [self.postBody, self.cw, self.visibility, self.post, self.discard], 0
        )

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        lines: List[Tuple[str, List[ControlCodes]]] = []

        # First, create the top "Posting as" section.
        lines.append(
            join(
                [
                    highlight(f"{self.verb.capitalize()}ing as "),
                    account(
                        self.properties["account"]["display_name"],
                        self.properties["account"]["username"],
                        self.renderer.columns - (9 + len(self.verb)),
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
        lines.append(join([highlight(" " * (13 + len(self.verb))), visibilityLines[0]]))
        lines.append(join([highlight(f"{self.verb.capitalize()} Visibility: "), visibilityLines[1]]))
        lines.append(join([highlight(" " * (13 + len(self.verb))), visibilityLines[2]]))

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

        elif inputVal == Terminal.LEFT and self.focusWrapper.component == 4:
            # Go from discard to post button.
            self.focusWrapper.previous()

            return NullAction()

        elif inputVal == Terminal.RIGHT and self.focusWrapper.component == 3:
            # Go from post to discard button.
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
                status = emoji.emojize(self.postBody.text)
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

                if self.edit:
                    self.properties['last_post'] = self.client.updatePost(self.edit, status, cw=cw)
                    self.renderer.status("Existing status updated! Drawing...")
                else:
                    self.properties['last_post'] = self.client.createPost(status, visibility, inReplyTo=self.inReplyTo, cw=cw)
                    self.renderer.status("New status posted! Drawing...")

                # Go back now, once post was successfully posted.
                return BackAction()
            elif self.focusWrapper.component == 4:
                # Client wants to discard their post. Confirm with them if they made edits.
                if self.postBody.text != self.originalText:
                    def yes() -> Action:
                        if self.exitMessage:
                            self.renderer.status(self.exitMessage)
                        return BackAction(depth=2)

                    return SwapScreenAction(
                        spawnConfirmationScreen,
                        text=f"Are you sure you want to discard this {self.verb}? This action cannot be undone!",
                        yes=yes,
                    )
                else:
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
        elif inputVal == Terminal.LEFT and self.focusWrapper.component == 3:
            # Go from quit to login button.
            self.focusWrapper.previous()
            return NullAction()
        elif inputVal == Terminal.RIGHT and self.focusWrapper.component == 2:
            # Go from login to quit button.
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


class ConfirmationComponent(Component):
    def __init__(
        self,
        renderer: Renderer,
        top: int,
        bottom: int,
        *,
        text: str = "",
        yes: Callable[[], Optional[Action]] = lambda : None,
        no: Callable[[], Optional[Action]] = lambda : None,
    ) -> None:
        super().__init__(renderer, top, bottom)

        # Set up which component we're on, defaulting to the no option.
        self.left = (self.renderer.terminal.columns // 2) - 20
        self.right = self.renderer.terminal.columns - self.left
        component = 1

        # Set up for what input we're handling.
        self.confirm = Button(
            renderer,
            "yes",
            (self.top - 1) + 12,
            self.left + 2,
            focused=component == 0,
        )
        self.cancel = Button(
            renderer,
            "no",
            (self.top - 1) + 12,
            self.left + 34,
            focused=component == 1,
        )

        self.focusWrapper = FocusWrapper(
            [self.confirm, self.cancel], component
        )
        self.text = text
        self.yes = yes
        self.no = no

    def __summonBox(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, create the "yes" and "no" buttons.
        yes = self.confirm.lines
        no = self.cancel.lines

        # Now, create the "middle bit" between the buttons.
        middle = highlight(pad("", 36 - 5 - 4))

        # Create the text lines themselves.
        text, codes = highlight(self.text + "\n\n\n\n\n\npadding")
        textlines = wordwrap(text, codes, 36)[:6]

        # Now, create the prompt box itself.
        lines = [
            boxtop(38),
            *[boxmiddle(textline, 38) for textline in textlines],
            *[
                boxmiddle(join([yes[x], middle, no[x]]), 38)
                for x in range(len(yes))
            ],
            boxbottom(38),
        ]

        return lines

    def draw(self) -> None:
        # Don't clear the screen, so this can pop over the existing drawn content.
        lines = self.__summonBox()
        bounds = BoundingRectangle(
            top=(self.top - 1) + 5,
            bottom=(self.top - 1) + 16,
            left=self.left + 1,
            right=self.right + 1,
        )
        display(self.terminal, lines, bounds)

        # Finally, display the status.
        self.renderer.status("Use tab to move between options.")

        # Now, put the cursor in the right spot.
        self.focusWrapper.focus()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal in {Terminal.LEFT, Terminal.UP}:
            # Go to previous component.
            self.focusWrapper.previous()

            return NullAction()
        elif inputVal in {Terminal.RIGHT, Terminal.DOWN}:
            # Go to next component.
            self.focusWrapper.next()

            return NullAction()
        elif inputVal == b"\r":
            # Ignore this.
            return NullAction()
        elif inputVal == b"\t":
            # Client pressed tab.
            self.focusWrapper.next(wrap=True)

            return NullAction()
        elif inputVal == b"\n":
            # Client pressed enter.
            if self.focusWrapper.component in {0, 1}:
                # Run the callback, and then exit.
                if self.focusWrapper.component == 0:
                    resp = self.yes()
                elif self.focusWrapper.component == 1:
                    resp = self.no()
                else:
                    resp = NullAction()

                if resp is not None:
                    return resp
                else:
                    return BackAction()

            return NullAction()
        else:
            return self.focusWrapper.processInput(inputVal)


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
        self.renderer.status("Press [left] or [backspace] to go back to the previous screen.")
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
        if inputVal in {Terminal.LEFT, Terminal.BACKSPACE}:
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


def spawnConfirmationScreen(
    renderer: Renderer, *, text: str = "", yes: Callable[[], None] = lambda : None, no: Callable[[], None] = lambda : None,
) -> None:
    renderer.push([ConfirmationComponent(renderer, top=1, bottom=renderer.rows, text=text, yes=yes, no=no)])


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


def spawnPostAndRepliesScreen(
    renderer: Renderer, *, post: Optional[StatusDict] = None
) -> None:
    renderer.push([PostViewComponent(renderer, top=1, bottom=renderer.rows, postId=post['id'] if post else 0)])


def spawnPostScreen(renderer: Renderer, edit: Optional[StatusDict] = None, replyTo: Optional[StatusDict] = None, exitMessage: str = "") -> None:
    renderer.push([ComposePostComponent(renderer, top=1, bottom=renderer.rows, edit=edit, inReplyTo=replyTo, exitMessage=exitMessage)])


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
