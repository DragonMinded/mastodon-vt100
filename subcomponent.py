import emoji
from abc import ABC
from datetime import datetime
from tzlocal import get_localzone

from vtpy import Terminal

from action import Action, NullAction, FOCUS_INPUT, UNFOCUS_INPUT
from clip import BoundingRectangle
from drawhelpers import (
    boost,
    account,
    boxtop,
    boxmiddle,
    boxbottom,
    replace,
)
from renderer import Renderer
from text import (
    ControlCodes,
    display,
    highlight,
    html,
    striplow,
    wordwrap,
    pad,
    obfuscate,
    center,
)

from typing import Any, Dict, List, Optional, Tuple


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

            # Stats formatting.
            stats = self.__format_stats(self.data["created_at"], reblog)

            # Now, surround the post in a box.
            self.lines = [
                boxtop(renderer.columns),
                *[boxmiddle(line, renderer.columns) for line in textlines],
                replace(boxbottom(renderer.columns), stats, offset=-2),
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

            # Stats formatting.
            stats = self.__format_stats(self.data["created_at"], self.data)

            # Now, surround the post in a box.
            self.lines = [
                boxtop(renderer.columns),
                *[boxmiddle(line, renderer.columns) for line in textlines],
                replace(boxbottom(renderer.columns), stats, offset=-2),
            ]

        self.height = len(self.lines)

    def __format_stats(
        self,
        timestamp: datetime,
        data: Dict[str, Any],
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
            stats.append(f"<bold>{self.data['reblogs_count']} R</bold>")
        else:
            stats.append(f"{self.data['reblogs_count']} R")

        # Likes
        if self.data["favourited"]:
            stats.append(f"<bold>{self.data['favourites_count']} L</bold>")
        else:
            stats.append(f"{self.data['favourites_count']} L")

        # Bookmarks
        if self.data["bookmarked"]:
            stats.append("<bold>B</bold>")
        else:
            stats.append("B")

        return highlight("\u2524" + "\u251c\u2500\u2524".join(stats) + "\u251c")

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
            postText = f"\u2524{postno}\u251c"
        else:
            postText = "\u2500\u2500\u2500"
        self.lines[0] = replace(self.lines[0], postText, offset=2)

        bounds = BoundingRectangle(
            top=top, bottom=bottom + 1, left=1, right=self.renderer.columns + 1
        )
        display(self.renderer.terminal, self.lines[offset:], bounds)


class Focusable(ABC):
    def processInput(self, inputVal: bytes) -> Optional[Action]:
        ...


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
        self, renderer: "Renderer", caption: str, row: int, column: int, *, focused: bool = False
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
            boxmiddle(highlight(f"<b>{self.caption}</b>" if self.focused else self.caption), width),
            boxbottom(width),
        ]

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row, bottom=self.row + 3, left=self.column, right=self.column + len(self.caption) + 2,
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
                    right=self.column + len(self.caption) + 2
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
                    right=self.column + len(self.caption) + 2
                )
                display(self.renderer.terminal, self.lines[1:2], bounds)

            return NullAction()

        return None


class HorizontalSelect(Focusable):
    def __init__(
        self, renderer: "Renderer", choices: List[str], row: int, column: int, width: int, *, selected: Optional[str] = None, focused: bool = False
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
            top=self.row, bottom=self.row + 3, left=self.column, right=self.column + self.width,
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
        self, renderer: "Renderer", text: str, row: int, column: int, length: int, *, obfuscate: bool = False
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
            top=self.row, bottom=self.row + 1, left=self.column, right=self.column + self.length
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
        self, renderer: "Renderer", text: str, row: int, column: int, width: int, height: int,
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
        lines = wordwrap(self.text, [code] * len(self.text), self.width)
        lines = lines[:self.height]

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

    def __moveCursor(self) -> None:
        # Calculate where the cursor actually is.
        lines = wordwrap(self.text, self.text, self.width)
        text = "\n".join(t for t, _ in lines)

        row = self.row
        column = self.column
        for i in range(self.cursor):
            if text[i] == "\n":
                row += 1
                column = self.column
            else:
                column += 1

        self.renderer.terminal.moveCursor(row, column)

    def draw(self) -> None:
        bounds = BoundingRectangle(
            top=self.row, bottom=self.row + self.height, left=self.column, right=self.column + self.width
        )
        display(self.renderer.terminal, self.lines, bounds)
        self.__moveCursor()

    def processInput(self, inputVal: bytes) -> Optional[Action]:
        if inputVal == FOCUS_INPUT:
            self.__moveCursor()
            return NullAction()

        return None
