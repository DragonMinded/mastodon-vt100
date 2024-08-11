import emoji
from abc import ABC
from datetime import datetime
from tzlocal import get_localzone

from typing import List, Optional, Set, Tuple

from vtpy import Terminal

from .action import Action, NullAction, FOCUS_INPUT, UNFOCUS_INPUT
from .client import StatusDict, MediaDict
from .clip import BoundingRectangle
from .drawhelpers import (
    account,
    boost,
    boxtop,
    boxmiddle,
    boxbottom,
    join,
    replace,
)
from .renderer import Renderer
from .text import (
    ControlCodes,
    display,
    highlight,
    html,
    striplow,
    wordwrap,
    pad,
    obfuscate,
    spoiler,
    center,
)


class PostThreadInfo:
    def __init__(
        self,
        level: int,
        highlighted: bool,
        hasDescendants: bool,
        hasAncestors: bool,
        hasParent: bool,
        hasSiblings: bool,
        siblingLevels: Set[int],
    ) -> None:
        self.level = level
        self.highlighted = highlighted
        self.hasDescendants = hasDescendants
        self.hasAncestors = hasAncestors
        self.hasParent = hasParent
        self.hasSiblings = hasSiblings
        self.siblingLevels = siblingLevels


class TimelinePost:
    def __init__(self, renderer: "Renderer", data: StatusDict, threadInfo: Optional[PostThreadInfo] = None) -> None:
        self.renderer = renderer
        self.data = data
        self.threadInfo = threadInfo or PostThreadInfo(
            0,
            False,
            False,
            False,
            False,
            False,
            set(),
        )
        self.width = renderer.columns - (3 * self.threadInfo.level)

        reblog = self.data["reblog"]
        if reblog:
            # First, start with the name of the reblogger.
            name = emoji.demojize(striplow(self.data["account"]["display_name"]))
            username = emoji.demojize(striplow(self.data["account"]["acct"]))
            self.boostline = [boost(name, username, self.width - 2)]

            # Now, grab the original name.
            name = emoji.demojize(striplow(reblog["account"]["display_name"]))
            username = emoji.demojize(striplow(reblog["account"]["acct"]))
            self.nameline = account(name, username, self.width - 2)

            content = emoji.demojize(striplow(reblog["content"]))
            content, codes = html(content)
            self.spoilerText = [
                content,
                spoiler(content),
            ]
            self.spoilerCodes = codes

            # Format the spoiler text if it exists.
            if reblog["spoiler_text"]:
                self.cwlines = [
                    highlight(
                        "<r>"
                        + pad(
                            "CW: " + striplow(reblog["spoiler_text"]),
                            self.width - 2,
                        )
                        + "</r>"
                    )
                ]
                self.spoilered = True
                self.spoilerNeeded = True
            else:
                self.cwlines = []
                self.spoilered = False
                self.spoilerNeeded = False

            # Stats formatting.
            self.stats = self.__format_stats(self.data["created_at"], reblog)
            self.attachments = self.__format_attachments(reblog["media_attachments"])

        else:
            # First, start with the name of the account.
            name = emoji.demojize(striplow(self.data["account"]["display_name"]))
            username = emoji.demojize(striplow(self.data["account"]["acct"]))
            self.nameline = account(name, username, self.width - 2)

            # No boost line here.
            self.boostline = []

            content = emoji.demojize(striplow(self.data["content"]))
            content, codes = html(content)
            self.spoilerText = [
                content,
                spoiler(content),
            ]
            self.spoilerCodes = codes

            # Format the spoiler text if it exists.
            if self.data["spoiler_text"]:
                self.cwlines = [
                    highlight(
                        "<r>"
                        + pad(
                            "CW: " + striplow(self.data["spoiler_text"]),
                            self.width - 2,
                        )
                        + "</r>"
                    )
                ]
                self.spoilered = True
                self.spoilerNeeded = True
            else:
                self.cwlines = []
                self.spoilered = False
                self.spoilerNeeded = False

            # Stats formatting.
            self.stats = self.__format_stats(self.data["created_at"], self.data)
            self.attachments = self.__format_attachments(self.data["media_attachments"])

        self.lines = self.__format_lines()
        self.height = len(self.lines)

    def __prefix(self, body: Tuple[str, List[ControlCodes]]) -> Tuple[str, List[ControlCodes]]:
        return join([highlight("   " * self.threadInfo.level), body])

    def __format_lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        # Format postbody
        postbody = wordwrap(
            self.spoilerText[1] if self.spoilered else self.spoilerText[0],
            self.spoilerCodes,
            self.width - 2,
        )

        # Actual contents.
        textlines = [
            *self.boostline,
            self.nameline,
            *self.cwlines,
            *postbody,
            *self.attachments,
        ]

        # Now, surround the post in a box.
        formattedlines = [
            self.__prefix(boxtop(self.width)),
            *[self.__prefix(boxmiddle(line, self.width)) for line in textlines],
            self.__prefix(replace(boxbottom(self.width), self.stats, offset=-2)),
        ]

        # Now, if this is highlighted, display that.
        if self.threadInfo.highlighted:
            highlightText = highlight("\u2524<b>current</b>\u251c")
            formattedlines[0] = replace(formattedlines[0], highlightText, offset=7 + (3 * self.threadInfo.level))

        # Now, decorate the box with any sort of threading indicators.
        if self.threadInfo.hasDescendants:
            formattedlines[-1] = replace(formattedlines[-1], "\u252c", 1 + (3 * self.threadInfo.level))
        if self.threadInfo.hasAncestors:
            formattedlines[0] = replace(formattedlines[0], "\u2534", 1 + (3 * self.threadInfo.level))
        if self.threadInfo.hasParent:
            formattedlines[0] = replace(formattedlines[0], "\u2502", (3 * self.threadInfo.level) - 2)
            formattedlines[1] = replace(
                formattedlines[1],
                "\u251c\u2500\u2524" if self.threadInfo.hasSiblings else "\u2514\u2500\u2524",
                (3 * self.threadInfo.level) - 2,
            )
        if self.threadInfo.hasSiblings:
            for i in range(2, len(formattedlines)):
                formattedlines[i] = replace(formattedlines[i], "\u2502", (3 * self.threadInfo.level) - 2)

        for level in self.threadInfo.siblingLevels:
            for i in range(len(formattedlines)):
                formattedlines[i] = replace(formattedlines[i], "\u2502", (3 * level) - 2)

        return formattedlines

    def __format_stats(
        self,
        timestamp: datetime,
        data: StatusDict,
    ) -> Tuple[str, List[ControlCodes]]:
        stats: List[str] = []

        # Timestamp
        stats.append(
            timestamp.astimezone(get_localzone())
            .strftime("%a, %b %d, %Y, %I:%M:%S %p")
            .replace(" 0", " ")
        )

        # Replies
        stats.append(f"{self.data['replies_count']} C")

        # Reblogs
        if self.data["reblogged"]:
            stats.append(f"<bold>{self.data['reblogs_count']} B</bold>")
        else:
            stats.append(f"{self.data['reblogs_count']} B")

        # Likes
        if self.data["favourited"]:
            stats.append(f"<bold>{self.data['favourites_count']} L</bold>")
        else:
            stats.append(f"{self.data['favourites_count']} L")

        # Bookmarks
        if self.data["bookmarked"]:
            stats.append("<bold>S</bold>")
        else:
            stats.append("S")

        return highlight("\u2524" + "\u251c\u2500\u2524".join(stats) + "\u251c")

    def __format_attachments(
        self, attachments: List[MediaDict],
    ) -> List[Tuple[str, List[ControlCodes]]]:
        attachmentLines = []
        for attachment in attachments:
            alt = striplow(
                emoji.demojize(attachment["description"] or "no description"),
                allow_safe=True,
            )
            url = striplow((attachment["url"] or "").split("/")[-1])
            description, codes = highlight(f"<u>{url}</u>: ")
            description += alt
            codes += [codes[-1]] * len(alt)

            attachmentbody = wordwrap(description, codes, self.width - 4)
            attachmentLines += [
                boxtop(self.width - 2),
                *[
                    boxmiddle(line, self.width - 2)
                    for line in attachmentbody
                ],
                boxbottom(self.width - 2),
            ]

        return attachmentLines

    def toggle_spoiler(self) -> bool:
        if not self.spoilerNeeded:
            return False
        self.spoilered = not self.spoilered
        self.lines = self.__format_lines()
        return True

    def draw(self, top: int, bottom: int, offset: int, postno: Optional[int]) -> None:
        # Maybe there's a better way to do this? Maybe display() should take substitutions?
        if postno is not None:
            postText = f"\u2524{postno}\u251c"
        else:
            postText = "\u2500\u2500\u2500"
        self.lines[0] = replace(self.lines[0], postText, offset=3 + (3 * self.threadInfo.level))

        bounds = BoundingRectangle(
            top=top, bottom=bottom + 1, left=1, right=self.renderer.columns + 1
        )
        display(self.renderer.terminal, self.lines[offset:], bounds)


class Focusable(ABC):
    def processInput(self, inputVal: bytes) -> Optional[Action]: ...


class FocusWrapper:
    def __init__(self, subcomponents: List[Focusable], component: int) -> None:
        self.subcomponents = subcomponents
        self.component = component

    def focus(self) -> None:
        self.subcomponents[self.component].processInput(FOCUS_INPUT)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        return self.subcomponents[self.component].processInput(inputVal)

    def previous(self, wrap: bool = False) -> None:
        if self.component > 0:
            self.subcomponents[self.component].processInput(UNFOCUS_INPUT)
            self.component -= 1
            self.subcomponents[self.component].processInput(FOCUS_INPUT)
        elif wrap:
            self.subcomponents[self.component].processInput(UNFOCUS_INPUT)
            self.component = len(self.subcomponents) - 1
            self.subcomponents[self.component].processInput(FOCUS_INPUT)

    def next(self, wrap: bool = False) -> None:
        if self.component < (len(self.subcomponents) - 1):
            self.subcomponents[self.component].processInput(UNFOCUS_INPUT)
            self.component += 1
            self.subcomponents[self.component].processInput(FOCUS_INPUT)
        elif wrap:
            self.subcomponents[self.component].processInput(UNFOCUS_INPUT)
            self.component = 0
            self.subcomponents[self.component].processInput(FOCUS_INPUT)


class Button(Focusable):
    def __init__(
        self,
        renderer: "Renderer",
        caption: str,
        row: int,
        column: int,
        *,
        focused: bool = False,
    ):
        self.renderer = renderer
        self.caption = caption
        self.row = row
        self.column = column
        self.focused = focused

    @property
    def lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        width = len(self.caption) + 2
        return [
            boxtop(width),
            boxmiddle(
                highlight(f"<b>{self.caption}</b>" if self.focused else self.caption),
                width,
            ),
            boxbottom(width),
        ]

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row,
            bottom=self.row + 3,
            left=self.column,
            right=self.column + len(self.caption) + 2,
        )
        display(self.renderer.terminal, self.lines, bounds)
        if self.focused:
            self.renderer.terminal.moveCursor(self.row + 1, self.column + 1)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        oldFocus = self.focused
        if inputVal == FOCUS_INPUT:
            self.focused = True

            if not oldFocus:
                # Must draw focus bold.
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + len(self.caption) + 2,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

            # Move cursor to the right spot.
            self.renderer.terminal.moveCursor(self.row + 1, self.column + 1)
            return NullAction()

        elif inputVal == UNFOCUS_INPUT:
            self.focused = False

            if oldFocus:
                # Must draw unfocus normal.
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + len(self.caption) + 2,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

            return NullAction()

        return None


class HorizontalSelect(Focusable):
    def __init__(
        self,
        renderer: "Renderer",
        choices: List[str],
        row: int,
        column: int,
        width: int,
        *,
        selected: Optional[str] = None,
        focused: bool = False,
    ):
        self.renderer = renderer
        self.choices = choices
        self.row = row
        self.column = column
        self.width = width
        self.focused = focused
        self.__selected = 0
        if selected:
            for i, choice in enumerate(self.choices):
                if choice == selected:
                    self.__selected = i
                    break

    @property
    def selected(self) -> str:
        return self.choices[self.__selected]

    @property
    def lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        left = "<r>&lt;</r> " if self.focused else "&lt; "
        right = " <r>&gt;</r>" if self.focused else " &gt;"
        text = center(self.choices[self.__selected], self.width - 6)

        return [
            boxtop(self.width),
            boxmiddle(highlight(f"{left}{text}{right}"), self.width),
            boxbottom(self.width),
        ]

    def __moveCursor(self) -> None:
        if self.focused:
            text = center(self.choices[self.__selected], self.width - 6)
            lPos = 0
            while lPos < len(text) and text[lPos] == " ":
                lPos += 1

            self.renderer.terminal.moveCursor(self.row + 1, self.column + 3 + lPos)

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row,
            bottom=self.row + 3,
            left=self.column,
            right=self.column + self.width,
        )
        display(self.renderer.terminal, self.lines, bounds)
        self.__moveCursor()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        oldFocus = self.focused
        if inputVal == FOCUS_INPUT:
            self.focused = True

            if not oldFocus:
                # Must draw focus bold.
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + self.width,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

            # Move cursor to the right spot.
            self.__moveCursor()
            return NullAction()

        elif inputVal == UNFOCUS_INPUT:
            self.focused = False

            if oldFocus:
                # Must draw unfocus normal.
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + self.width,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

            return NullAction()

        elif inputVal == Terminal.LEFT:
            if self.__selected > 0:
                self.__selected -= 1
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + self.width,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

                # Move cursor to the right spot.
                self.__moveCursor()
            return NullAction()

        elif inputVal == Terminal.RIGHT:
            if self.__selected < len(self.choices) - 1:
                self.__selected += 1
                bounds = BoundingRectangle(
                    top=self.row + 1,
                    bottom=self.row + 2,
                    left=self.column,
                    right=self.column + self.width,
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

                # Move cursor to the right spot.
                self.__moveCursor()
            return NullAction()

        return None


class OneLineInputBox(Focusable):
    def __init__(
        self,
        renderer: "Renderer",
        text: str,
        row: int,
        column: int,
        length: int,
        *,
        obfuscate: bool = False,
    ) -> None:
        self.renderer = renderer
        self.text = text[:length]
        self.cursor = len(self.text)
        self.row = row
        self.column = column
        self.length = length
        self.obfuscate = obfuscate

    @property
    def lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        if self.obfuscate:
            return [highlight("<r>" + pad(obfuscate(self.text), self.length) + "</r>")]
        else:
            return [highlight("<r>" + pad(self.text, self.length) + "</r>")]

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row,
            bottom=self.row + 1,
            left=self.column,
            right=self.column + self.length,
        )
        display(self.renderer.terminal, self.lines, bounds)
        self.renderer.terminal.moveCursor(self.row, self.column + self.cursor)

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == Terminal.LEFT:
            if self.cursor > 0:
                self.cursor -= 1
                self.renderer.terminal.moveCursor(self.row, self.column + self.cursor)

            return NullAction()
        elif inputVal == Terminal.RIGHT:
            if self.cursor < len(self.text):
                self.cursor += 1
                self.renderer.terminal.moveCursor(self.row, self.column + self.cursor)

            return NullAction()
        elif inputVal == FOCUS_INPUT:
            self.renderer.terminal.moveCursor(self.row, self.column + self.cursor)
            return NullAction()

        elif inputVal in {Terminal.BACKSPACE, Terminal.DELETE}:
            if self.text:
                # Just subtract from input.
                if self.cursor == len(self.text):
                    # Erasing at the end of the line.
                    self.text = self.text[:-1]

                    self.cursor -= 1
                    self.draw()
                elif self.cursor == 0:
                    # Erasing at the beginning, do nothing.
                    pass
                elif self.cursor == 1:
                    # Erasing at the beginning of the line.
                    self.text = self.text[1:]

                    self.cursor -= 1
                    self.draw()
                else:
                    # Erasing in the middle of the line.
                    spot = self.cursor - 1
                    self.text = self.text[:spot] + self.text[(spot + 1) :]

                    self.cursor -= 1
                    self.draw()

            return NullAction()
        else:
            # If we got some unprintable character, ignore it.
            inputVal = bytes(v for v in inputVal if v >= 0x20 and v < 0x80)
            if inputVal:
                if len(self.text) < (self.length - 1):
                    # Just add to input.
                    char = inputVal.decode("ascii")

                    if self.cursor == len(self.text):
                        # Just appending to the input.
                        self.text += char
                        self.cursor += 1
                        self.draw()
                    else:
                        # Adding to mid-input.
                        spot = self.cursor
                        self.text = self.text[:spot] + char + self.text[spot:]
                        self.cursor += 1
                        self.draw()

                return NullAction()

            # For control characters, don't claim we did anything with them, so parent
            # components can act on them.
            return None

        return None


class MultiLineInputBox(Focusable):
    def __init__(
        self,
        renderer: "Renderer",
        text: str,
        row: int,
        column: int,
        width: int,
        height: int,
    ) -> None:
        self.renderer = renderer
        self.text = text
        self.cursor = len(self.text)
        self.row = row
        self.column = column
        self.width = width
        self.height = height
        self.obfuscate = obfuscate

    @property
    def lines(self) -> List[Tuple[str, List[ControlCodes]]]:
        # First, word wrap to put the text in the right spot.
        code = ControlCodes(reverse=True)
        lines = wordwrap(
            self.text,
            [code] * len(self.text),
            self.width - 1,
            strip_trailing_spaces=False,
        )
        lines = lines[: self.height]

        # Now, make sure any unfilled lines are drawn.
        while len(lines) < self.height:
            lines.append((" " * self.width, [code] * self.width))

        # We must make sure that each line is padded out to the right length.
        output: List[Tuple[str, List[ControlCodes]]] = []
        for i in range(len(lines)):
            text, codes = lines[i]
            amount = self.width - len(text)
            if amount > 0:
                output.append((text + (" " * amount), [*codes, *([code] * amount)]))
            else:
                output.append((text, list(codes)))

        return output

    def __calcCursorPositions(
        self, text: str, positions: List[int]
    ) -> List[Tuple[int, Tuple[int, int]]]:
        row = self.row
        column = self.column
        cursorPositions: List[Tuple[int, Tuple[int, int]]] = []
        for i, pos in enumerate(positions):
            cursorPositions.append((pos, (row, column)))

            if i == len(text):
                break
            if text[i] == "\n":
                row += 1
                column = self.column
            else:
                column += 1

        return cursorPositions

    def __moveCursor(self) -> None:
        # Calculate where the cursor actually is.
        text, _, positions = self.__calcTextAndPositions()

        row = self.row
        column = self.column
        for i in range(len(positions)):
            if positions[i] == self.cursor:
                break

            if text[i] == "\n":
                row += 1
                column = self.column
            else:
                column += 1
        self.renderer.terminal.moveCursor(row, column)

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row,
            bottom=self.row + self.height,
            left=self.column,
            right=self.column + self.width,
        )
        display(self.renderer.terminal, self.lines, bounds)
        self.__moveCursor()

    def __calcTextAndPositions(self) -> Tuple[str, List[str], List[int]]:
        # We need to know what changed so we can redraw if necessary.
        linesAndCodes = wordwrap(
            self.text,
            [i for i in range(len(self.text))],
            self.width - 1,
            strip_trailing_spaces=False,
            strip_trailing_newlines=False,
        )
        lines = [line for line, _ in linesAndCodes]
        codes = [code for _, code in linesAndCodes]

        # Calculate actual displayed text and its length.
        text = "\n".join(lines)

        # Calculate actual text position given cursor position
        positions: List[int] = []
        for codeblock in codes:
            if positions:
                handled = False

                if codeblock:
                    # This is a space or user-entered newline that caused us to wrap.
                    if codeblock[0] - positions[-1] >= 2 and self.text[
                        positions[-1] + 1
                    ] in {" ", "\n"}:
                        positions.append(positions[-1] + 1)
                        handled = True

                    # This is a word that was wrapped mid-line.
                    elif codeblock[0] - positions[-1] == 1:
                        positions.append(-1)
                        handled = True

                else:
                    # This might be a user-entered newline that caused us to wrap.
                    if self.text[positions[-1] + 1] in {" ", "\n"}:
                        positions.append(positions[-1] + 1)
                        handled = True

                if not handled:
                    raise Exception("Logic error, unknown state!")

            positions.extend(codeblock)

        # Account for trailing whitespace and newlines.
        if self.text:
            if positions[-1] == -1:
                raise Exception("Logic error, unknown state!")
            while positions[-1] < len(self.text):
                positions.append(positions[-1] + 1)
        else:
            if positions:
                raise Exception("Logic error, positions should be empty!")
            positions.append(0)

        if (len(text) + 1) != len(positions):
            raise Exception("Logic error, inconsistent position calculation!")

        return text, lines, positions

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        # First, grab our cursor positions.
        text, lines, positions = self.__calcTextAndPositions()

        # Keep track of whether we need to compute redraw or not.
        handled = False
        cursor = 0
        for i, pos in enumerate(positions):
            if pos == self.cursor:
                cursor = i
                break

        if inputVal == Terminal.LEFT:
            if cursor > 0:
                cursor -= 1
                while cursor > 0 and positions[cursor] == -1:
                    cursor -= 1

                self.cursor = positions[cursor]
                self.__moveCursor()

            return NullAction()

        elif inputVal == Terminal.RIGHT:
            if cursor < len(text):
                cursor += 1
                while cursor < len(text) and positions[cursor] == -1:
                    cursor += 1

                self.cursor = positions[cursor]
                self.__moveCursor()

            return NullAction()

        elif inputVal == Terminal.UP:
            cursorPositions = self.__calcCursorPositions(text, positions)
            _, (curRow, curColumn) = cursorPositions[cursor]

            possiblePositions = [
                c
                for c in cursorPositions
                if (c[1][0] == curRow - 1) and (c[1][1] <= curColumn)
            ]
            if possiblePositions:
                # Take the closest to the cursor.
                newCursor, _ = possiblePositions[-1]

                self.cursor = newCursor
                self.__moveCursor()

            return NullAction()

        elif inputVal == Terminal.DOWN:
            cursorPositions = self.__calcCursorPositions(text, positions)
            _, (curRow, curColumn) = cursorPositions[cursor]

            possiblePositions = [
                c
                for c in cursorPositions
                if (c[1][0] == curRow + 1) and (c[1][1] <= curColumn)
            ]
            if possiblePositions:
                # Take the closest to the cursor.
                newCursor, _ = possiblePositions[-1]

                self.cursor = newCursor
                self.__moveCursor()

            return NullAction()

        elif inputVal == FOCUS_INPUT:
            self.__moveCursor()
            return NullAction()

        elif inputVal in {Terminal.BACKSPACE, Terminal.DELETE}:
            if self.text:
                # Just subtract from input.
                if cursor == len(text):
                    # Erasing at the end of the text.
                    self.text = self.text[:-1]
                    self.cursor -= 1

                elif cursor == 0:
                    # Erasing at the beginning, do nothing.
                    pass

                else:
                    # Erasing in the middle of the text.
                    while positions[cursor - 1] == -1:
                        cursor -= 1
                        if cursor < 0:
                            raise Exception("Logic error, cannot find erase point!")

                    spot = positions[cursor - 1]
                    self.text = self.text[:spot] + self.text[(spot + 1) :]
                    self.cursor -= 1

            handled = True

        else:
            # If we got some unprintable character, ignore it.
            inputVal = bytes(
                v for v in inputVal if (v == 0x0A or (v >= 0x20 and v < 0x80))
            )
            if inputVal:
                # Just add to input.
                char = inputVal.decode("ascii")

                if cursor == len(text):
                    # Just appending to the input.
                    self.text += char
                    self.cursor += 1
                else:
                    # Adding to mid-input.
                    spot = positions[cursor]

                    # Adding to a normal spot.
                    self.text = self.text[:spot] + char + self.text[spot:]
                    self.cursor += 1

                handled = True

        if not handled:
            # For control characters, don't claim we did anything with them, so parent
            # components can act on them.
            return None

        # Need to calculate the new lines, and display ones that changed.
        newLinesAndCodes = wordwrap(
            self.text,
            self.text,
            self.width - 1,
            strip_trailing_spaces=False,
            strip_trailing_newlines=False,
        )
        newLines = [line for line, _ in newLinesAndCodes]
        oldLineLength = len(lines)
        newLineLength = len(newLines)

        drawableLines = self.lines
        for i in range(min(oldLineLength, newLineLength)):
            if lines[i] != newLines[i]:
                # We need to draw this line, but possibly not the whole line.
                firstDiff = -1
                lastDiff = -1
                oldLength = len(lines[i])
                newLength = len(newLines[i])

                for j in range(min(oldLength, newLength)):
                    if lines[i][j] != newLines[i][j]:
                        if firstDiff == -1:
                            firstDiff = j
                        lastDiff = j + 1
                if oldLength != newLength:
                    lastDiff = max(oldLength, newLength)
                if firstDiff == -1:
                    firstDiff = min(oldLength, newLength)

                # Only draw what we need to on the screen, being as minimal as possible for faster refresh.
                bounds = BoundingRectangle(
                    top=self.row + i,
                    bottom=self.row + i + 1,
                    left=self.column + firstDiff,
                    right=self.column + lastDiff,
                )
                drawableLine, drawableCodes = drawableLines[i]
                drawableLine = drawableLine[firstDiff:]
                drawableCodes = drawableCodes[firstDiff:]
                display(self.renderer.terminal, [(drawableLine, drawableCodes)], bounds)

        if oldLineLength != newLineLength:
            # Need to redraw the last lines.
            for i in range(
                min(oldLineLength, newLineLength), max(oldLineLength, newLineLength)
            ):
                # We need to draw this line.
                bounds = BoundingRectangle(
                    top=self.row + i,
                    bottom=self.row + i + 1,
                    left=self.column,
                    right=self.column + self.width,
                )
                display(self.renderer.terminal, drawableLines[i : (i + 1)], bounds)

        # Now, stick the cursor back.
        self.__moveCursor()

        return NullAction()
