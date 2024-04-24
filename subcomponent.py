import emoji
from datetime import datetime
from tzlocal import get_localzone

from vtpy import Terminal

from action import Action, NullAction, FOCUS_INPUT
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
        elif inputVal == FOCUS_INPUT:
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
            # If we got some unprintable character, ignore it.
            inputVal = bytes(v for v in inputVal if v >= 0x20)
            if inputVal:
                if len(self.text) < (self.length - 1):
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

            # For control characters, don't claim we did anything with them, so parent
            # components can act on them.
            return None

        return None
