import sys
from html.parser import HTMLParser
from typing import Any, List, Optional, Tuple, TypeVar

from vtpy import Terminal

from .clip import BoundingRectangle


class ControlCodes:
    def __init__(
        self, *, bold: bool = False, underline: bool = False, reverse: bool = False
    ) -> None:
        self.bold = bold
        self.underline = underline
        self.reverse = reverse

    def codesFrom(self, prev: "ControlCodes") -> List[bytes]:
        if (
            ((not self.bold) and prev.bold)
            or ((not self.underline) and prev.underline)
            or ((not self.reverse) and prev.reverse)
        ):
            # If we're turning anything off, then we need to turn everything off and then re-enable
            # only what we care about.
            resetcodes: List[bytes] = [Terminal.SET_NORMAL]

            if self.bold:
                resetcodes.append(Terminal.SET_BOLD)
            if self.underline:
                resetcodes.append(Terminal.SET_UNDERLINE)
            if self.reverse:
                resetcodes.append(Terminal.SET_REVERSE)

            return resetcodes
        else:
            # If we're turning nothing off, and possibly turning something on, then we only need to emit codes for that.
            normalcodes: List[bytes] = []

            if (not prev.bold) and self.bold:
                normalcodes.append(Terminal.SET_BOLD)
            if (not prev.underline) and self.underline:
                normalcodes.append(Terminal.SET_UNDERLINE)
            if (not prev.reverse) and self.reverse:
                normalcodes.append(Terminal.SET_REVERSE)

            return normalcodes


ConcatableSequence = TypeVar('ConcatableSequence', List[Any], str)


def wordwrap(
    text: str,
    meta: ConcatableSequence,
    width: int,
    *,
    strip_trailing_spaces: bool = True,
    strip_trailing_newlines: bool = True,
) -> List[Tuple[str, ConcatableSequence]]:
    """
    Given a text string and a maximum allowed width, word-wraps that text by
    returning a list of lines, none of which are longer than the specified
    width. Prefers embedded newlines, then space, then wrapping at the first
    alphanumeric character after punctuation, and finally mid-word if it must.
    Note that this algorithm treats text similar to how a browser would, where
    whitespace is considered for spacing words apart from each other, not for
    positional formatting.
    """

    if not text:
        # Hack just in case meta is a string.
        return [(text[:0], meta[:0])]

    if len(text) != len(meta):
        raise Exception("Metadata length must match text length!")

    outLines: List[Tuple[str, ConcatableSequence]] = []

    # We don't handle non-unix line endings, so convert them.
    text = text.replace("\r\n", "{\x01\x02\x03}")
    text = text.replace("\r", "\n")
    text = text.replace("{\x01\x02\x03}", "\r\n")

    # First, go through and replace all tabs with the correct number of spaces.
    lineLength = 0
    newText = ""
    newMeta = meta[:0]

    for i, c in enumerate(text):
        if c == "\t":
            numSpaces = 4 - (lineLength % 4)
            lineLength += numSpaces
            newText += " " * numSpaces
            for _ in range(numSpaces):
                newMeta += meta[i:i + 1]
        elif c == "\r":
            # This is a vestige at this point, because all \r that aren't attached
            # to \n are gone.
            pass
        elif c == "\n":
            newText += c
            newMeta += meta[i:i + 1]
            lineLength = 0
        else:
            newText += c
            newMeta += meta[i:i + 1]
            lineLength += 1
    text = newText
    meta = newMeta

    # Hack to support trailing newlines properly.
    if text and text[-1] == "\n":
        text += "\x08"
        meta += meta[-1:]

    if len(text) != len(meta):
        raise Exception("Logic error! Metadata length must match text length!")

    # Now, go through and find any potential wrap points.
    wrapPoints: List[int] = []
    lastPunctuation = False

    for i, ch in enumerate(text):
        if ch in {" ", "\n"}:
            lastPunctuation = False
            wrapPoints.append(i)
        elif ch in {"-"}:
            # List of punctuation marks that are allowed to be wrappers. Right now
            # only the dash is included here, so parenthesis stick with their
            # respective words.
            lastPunctuation = True
        elif ch.isalnum():
            if lastPunctuation:
                wrapPoints.append(i)
            lastPunctuation = False

    # Now, repeatedly separate out lines using our wrap points, and possibly
    # in the middle of a word if we don't have any choice.
    while text:
        relevantPoints = [x for x in wrapPoints if x <= width]

        # First, check if any of these is a newline, we preference these.
        newLine = False
        for pos in relevantPoints:
            if text[pos] == "\n":
                # Add up to the newline, but not including the newline.
                outLines.append((text[:pos], meta[:pos]))

                # Cut off the text and metadata up through the newline, so that
                # the remaining bits are the next character+meta after.
                text = text[(pos + 1) :]
                meta = meta[(pos + 1) :]

                # Filter out irrelevant wrap points and fix up their locations. We keep
                # zero-location word-wrap points after this because text could include
                # multiple newlines.
                wrapPoints = [x - (pos + 1) for x in wrapPoints if (x - (pos + 1)) >= 0]

                newLine = True
                break

        if newLine:
            # We already handled this, try again.
            continue

        # Now, since there wasn't a newline to handle, we pick the highest
        # candidate wrap point that's available. Don't do this if the text is
        # going to fit on it's own.
        if (len(text) > width) and relevantPoints:
            pos = relevantPoints[-1]

            if text[pos] == " ":
                if strip_trailing_spaces:
                    # We don't include the space at the end of the line, or in the
                    # beginning of the next, so drop it.
                    outLines.append((text[:pos], meta[:pos]))

                    # Find the first non-space to wrap
                    spot = -1
                    for i in range(pos + 1, len(text)):
                        if text[i] != " ":
                            spot = i
                            break

                    if spot >= 0:
                        text = text[spot:]
                        meta = meta[spot:]

                        # Filter out irrelevant wrap points and fix up their locations. We keep
                        # zero-location word-wrap points after this because text could include
                        # multiple newlines.
                        wrapPoints = [x - spot for x in wrapPoints if (x - spot) >= 0]
                    else:
                        # We hit the end of the text.
                        text = ""
                        meta = meta[:0]
                        wrapPoints = []
                else:
                    # In one case, we strip trailing space if we're replacing it with a newline.
                    if pos == width and text[pos - 1] != " ":
                        outLines.append((text[:pos], meta[:pos]))

                        spot = pos + 1
                        text = text[spot:]
                        meta = meta[spot:]

                        if not text:
                            # If we ran out of text, we need to represent the next line as empty
                            # due to the aforementioned replacement with newline. If we're asked
                            # to strip newlines this will just go away anyway.
                            outLines.append((text[:0], meta[:0]))

                        # Filter out irrelevant wrap points and fix up their locations. We keep
                        # zero-location word-wrap points after this because text could include
                        # multiple newlines.
                        wrapPoints = [x - spot for x in wrapPoints if (x - spot) >= 0]
                    else:
                        # Find the first non-space to wrap
                        spot = len(text)
                        for i in range(pos + 1, len(text)):
                            if text[i] != " ":
                                spot = i
                                break

                        # If the spot we should wrap to is larger than the width, when we should
                        # insert an arbitrary wrap point at the width
                        if spot > width:
                            spot = width

                        outLines.append((text[:spot], meta[:spot]))
                        text = text[spot:]
                        meta = meta[spot:]

                        # Filter out irrelevant wrap points and fix up their locations. We keep
                        # zero-location word-wrap points after this because text could include
                        # multiple newlines.
                        wrapPoints = [x - spot for x in wrapPoints if (x - spot) >= 0]
            else:
                # We're wrapping mid-word, probably at a punctuation point, so we keep
                # everything on both sides.
                outLines.append((text[:pos], meta[:pos]))
                text = text[pos:]
                meta = meta[pos:]

                # Filter out irrelevant wrap points and fix up their locations. We keep
                # zero-location word-wrap points after this because text could include
                # multiple newlines.
                wrapPoints = [x - pos for x in wrapPoints if (x - pos) >= 0]
        else:
            # We have no choice but to wrap the text mid-word in a non-ideal location.
            outLines.append((text[:width], meta[:width]))
            text = text[width:]
            meta = meta[width:]

            # Filter out irrelevant wrap points and fix up their locations. We keep
            # zero-location word-wrap points after this because text could include
            # multiple newlines.
            wrapPoints = [x - width for x in wrapPoints if (x - width) >= 0]

    # Finally, get rid of trailing whitespace.
    def stripSpace(line: Tuple[str, ConcatableSequence]) -> Tuple[str, ConcatableSequence]:
        text, meta = line

        # Unhack the trailing newline hack.
        if text == "\x08":
            return (text[:0], meta[:0])

        if strip_trailing_spaces:
            while text and text[-1] in {" "}:
                text = text[:-1]
                meta = meta[:-1]

        return (text, meta)

    outLines = [stripSpace(line) for line in outLines]
    if strip_trailing_newlines:
        while outLines and (not outLines[-1][0]):
            outLines = outLines[:-1]
    return outLines


def __split_formatted_string(string: str) -> List[str]:
    accumulator: List[str] = []
    parts: List[str] = []

    for ch in string:
        if ch == "<":
            if accumulator:
                parts.append("".join(accumulator))
                accumulator = []
            accumulator.append(ch)
        elif ch == ">":
            accumulator.append(ch)
            if accumulator[0] == "<":
                parts.append("".join(accumulator))
                accumulator = []
        else:
            accumulator.append(ch)

    if accumulator:
        parts.append("".join(accumulator))
    return parts


def striplow(text: str, allow_safe: bool = False) -> str:
    for i in range(32):
        # Allow newline characters, allow tabs.
        if allow_safe and i in {9, 10}:
            continue
        text = text.replace(chr(i), "")
    return text


def sanitize(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def unsanitize(text: str) -> str:
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    return text


def highlight(text: str) -> Tuple[str, List[ControlCodes]]:
    parts = __split_formatted_string(text)
    cur = ControlCodes(bold=False, underline=False, reverse=False)

    bdepth = 0
    udepth = 0
    rdepth = 0

    texts: List[str] = []
    codes: List[ControlCodes] = []

    for part in parts:
        if part[:1] == "<" and part[-1:] == ">":
            # Control code modifier.
            if part in {"<b>", "<bold>"}:
                bdepth += 1
                if bdepth == 1:
                    cur = ControlCodes(
                        bold=True, underline=cur.underline, reverse=cur.reverse
                    )
            elif part in {"</b>", "</bold>"}:
                if bdepth == 1:
                    cur = ControlCodes(
                        bold=False, underline=cur.underline, reverse=cur.reverse
                    )
                bdepth -= 1
                if bdepth < 0:
                    bdepth = 0

            if part in {"<u>", "<underline>"}:
                udepth += 1
                if udepth == 1:
                    cur = ControlCodes(
                        bold=cur.bold, underline=True, reverse=cur.reverse
                    )
            elif part in {"</u>", "</underline>"}:
                if udepth == 1:
                    cur = ControlCodes(
                        bold=cur.bold, underline=False, reverse=cur.reverse
                    )
                udepth -= 1
                if udepth < 0:
                    udepth = 0

            if part in {"<r>", "<reverse>"}:
                rdepth += 1
                if rdepth == 1:
                    cur = ControlCodes(
                        bold=cur.bold, underline=cur.underline, reverse=True
                    )
            elif part in {"</r>", "</reverse>"}:
                if rdepth == 1:
                    cur = ControlCodes(
                        bold=cur.bold, underline=cur.underline, reverse=False
                    )
                rdepth -= 1
                if rdepth < 0:
                    rdepth = 0
        else:
            part = unsanitize(part)
            texts.append(part)
            codes.extend([cur] * len(part))

    return ("".join(texts), codes)


class MastodonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text = ""
        self.codes: List[ControlCodes] = []
        self.pending: Optional[ControlCodes] = None
        self.bdepth = 0
        self.udepth = 0
        self.rdepth = 0
        self.liststack: List[str] = []
        self.listcount: List[int] = []

    def __last_code(self) -> ControlCodes:
        if self.pending:
            code = self.pending
            self.pending = None
            return code
        if self.codes:
            return self.codes[-1]
        return ControlCodes(bold=False, underline=False, reverse=False)

    def __bold_last_code(self) -> ControlCodes:
        code = self.__last_code()

        self.bdepth += 1
        if self.bdepth == 1:
            return ControlCodes(
                bold=True, underline=code.underline, reverse=code.reverse
            )
        return code

    def __unbold_last_code(self) -> ControlCodes:
        code = self.__last_code()

        if self.bdepth == 1:
            self.bdepth = 0
            return ControlCodes(
                bold=False, underline=code.underline, reverse=code.reverse
            )
        elif self.bdepth > 0:
            self.bdepth -= 1
        return code

    def __underline_last_code(self) -> ControlCodes:
        code = self.__last_code()

        self.udepth += 1
        if self.udepth == 1:
            return ControlCodes(bold=code.bold, underline=True, reverse=code.reverse)
        return code

    def __ununderline_last_code(self) -> ControlCodes:
        code = self.__last_code()

        if self.udepth == 1:
            self.udepth = 0
            return ControlCodes(bold=code.bold, underline=False, reverse=code.reverse)
        elif self.udepth > 0:
            self.udepth -= 1
        return code

    def __reverse_last_code(self) -> ControlCodes:
        code = self.__last_code()

        self.rdepth += 1
        if self.rdepth == 1:
            return ControlCodes(bold=code.bold, underline=code.underline, reverse=True)
        return code

    def __unreverse_last_code(self) -> ControlCodes:
        code = self.__last_code()

        if self.rdepth == 1:
            self.rdepth = 0
            return ControlCodes(bold=code.bold, underline=code.underline, reverse=False)
        elif self.rdepth > 0:
            self.rdepth -= 1
        return code

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in {"p", "blockquote"}:
            code = self.__last_code()
            needsNewline = bool(self.text) and self.text[-1] != "\n"
            newLine = "\n" if needsNewline else ""

            if newLine:
                self.text += newLine
                self.codes += [code] * len(newLine)
        elif tag in {"span", "code"}:
            # Spans are just wrapper elements with no formatting. Code usually denotes
            # fixed width, but we literally only can do that.
            pass
        elif tag == "br":
            # Simple, handle this by adding.
            self.text += "\n"
            self.codes += [self.__last_code()]
        elif tag == "a":
            # Right now, just underline links.
            self.pending = self.__underline_last_code()
        elif tag == "b":
            # Bold it!
            self.pending = self.__bold_last_code()
        elif tag in {"i", "em"}:
            # Reverse the text for emphasis!
            self.pending = self.__reverse_last_code()
        elif tag == "u":
            # Underline it!
            self.pending = self.__underline_last_code()
        elif tag == "ul":
            # Unordered list start.
            self.liststack.append("ul")
            self.listcount.append(0)
        elif tag == "ol":
            # Ordered list start.
            self.liststack.append("ol")
            self.listcount.append(0)
        elif tag == "li":
            # Check if we're ordered or unordered.
            code = self.__last_code()
            needsNewline = bool(self.text) and self.text[-1] != "\n"
            newLine = "\n" if needsNewline else ""

            if self.liststack and self.listcount:
                if self.liststack[-1] == "ol":
                    # Counted list.
                    text = newLine + (" " * len(self.liststack)) + str(self.listcount[-1] + 1) + ". "
                    self.codes += [code] * len(text)
                    self.text += text
                elif self.liststack[-1] == "ul":
                    # Uncounted list. Add an indented middot.
                    text = newLine + (" " * len(self.liststack)) + "\xb7 "
                    self.codes += [code] * len(text)
                    self.text += text
                self.listcount[-1] += 1
        else:
            print("Unsupported start tag", tag, file=sys.stderr)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "blockquote"}:
            # Simple, handle this by adding.
            self.text += "\n\n"
            code = self.__last_code()
            self.codes += [code, code]
        elif tag == "a":
            # Right now, just underline links.
            self.pending = self.__ununderline_last_code()
        elif tag == "b":
            # Bold it!
            self.pending = self.__unbold_last_code()
        elif tag in {"i", "em"}:
            # Reverse the text for emphasis!
            self.pending = self.__unreverse_last_code()
        elif tag == "u":
            # Underline it!
            self.pending = self.__ununderline_last_code()
        elif tag in {"span", "code", "br"}:
            pass
        elif tag in {"ul", "ol"}:
            if self.liststack:
                self.liststack = self.liststack[:-1]
            if self.listcount:
                self.listcount = self.listcount[:-1]

            self.text += "\n\n"
            code = self.__last_code()
            self.codes += [code, code]

            if len(self.liststack) != len(self.listcount):
                # Never should hit this, so except on it so I can debug.
                raise Exception("Logic error, should never get out of sync!")
        elif tag == "li":
            # Nothing to do on close.
            pass
        else:
            print("Unsupported end tag", tag, file=sys.stderr)

    def handle_data(self, data: str) -> None:
        self.text += data
        code = self.__last_code()
        self.codes += [code] * len(data)

    def parsed(self) -> Tuple[str, List[ControlCodes]]:
        text = self.text
        codes = self.codes

        while text and text[0].isspace():
            text = text[1:]
            codes = codes[1:]
        while text and text[-1].isspace():
            text = text[:-1]
            codes = codes[:-1]

        return (text, codes)


def html(data: str) -> Tuple[str, List[ControlCodes]]:
    parser = MastodonParser()
    parser.feed(data)
    parser.close()

    return parser.parsed()


def display(
    terminal: Terminal,
    lines: List[Tuple[str, List[ControlCodes]]],
    bounds: BoundingRectangle,
) -> None:
    # Before anything, verify that the bounds is within the terminal, and if not, skip displaying it. We're
    # 1-based since that's what the VT-100 manual refers to the top left as (1, 1).
    if bounds.bottom <= 1:
        return
    if bounds.top > terminal.rows:
        return
    if bounds.right <= 1:
        return
    if bounds.left > terminal.columns:
        return

    # Now, if we're off the top or the right, then cut off that many bits of the top or left.
    if bounds.top < 1:
        amount = -(bounds.top - 1)
        lines = lines[amount:]
    if bounds.left < 1:
        amount = -(bounds.left - 1)
        lines = [(text[amount:], codes[amount:]) for (text, codes) in lines]

    # Now, clip the rectangle to the screen.
    bounds = bounds.clip(
        BoundingRectangle(
            left=1, top=1, right=terminal.columns + 1, bottom=terminal.rows + 1
        )
    )
    if bounds.width == 0 or bounds.height == 0:
        return

    # Clip off any lines that go off the bottom of the screen.
    lines = lines[: bounds.height]

    # Now, figure out where we left off last time we drew anything.
    last = ControlCodes(
        bold=terminal.bolded, underline=terminal.underlined, reverse=terminal.reversed
    )

    # Move to where we're drawing.
    row, col = terminal.fetchCursor()
    if row != bounds.top or col != bounds.left:
        if row == (bounds.top - 1) and bounds.left == 1:
            terminal.sendText("\n")
        else:
            terminal.moveCursor(bounds.top, bounds.left)
        row, col = (bounds.top, bounds.left)

    # Now, for each line, display the text up to the point where the bounds cuts off.
    for i, (text, codes) in enumerate(lines):
        # If this isn't the first line, move to the new line.
        if i != 0:
            # Shortcut to moving to the next line if the column is 1.
            row += 1
            col = bounds.left
            if col == 1:
                terminal.sendText("\n")
            else:
                terminal.moveCursor(row, col)

        # Now, make sure we don't trail off the right side of the terminal.
        text = text[: bounds.width]
        codes = codes[: bounds.width]

        # Finally, actually display the text.
        for pos in range(len(text)):
            for code in codes[pos].codesFrom(last):
                terminal.sendCommand(code)
            last = codes[pos]
            terminal.sendText(text[pos])

            # If we support wide text, this is where we would do it, by incrementing double.
            col += 1
            if col >= bounds.right:
                break


def pad(line: str, length: int) -> str:
    if len(line) >= length:
        return line[:length]
    amount = length - len(line)
    return line + (" " * amount)


def lpad(line: str, length: int) -> str:
    if len(line) >= length:
        return line[:length]
    amount = length - len(line)
    return (" " * amount) + line


def center(line: str, length: int) -> str:
    if len(line) == length:
        return line
    elif len(line) > length:
        leftCut = (len(line) - length) // 2
        line = line[leftCut:]
        return line[:length]
    else:
        leftAdd = (length - len(line)) // 2
        line = (" " * leftAdd) + line
        return pad(line, length)


def obfuscate(line: str) -> str:
    return "*" * len(line)


def spoiler(line: str) -> str:
    def conv(x: str) -> str:
        if ord(x) <= 32:
            return x
        if x.isspace():
            return x

        return "#"

    return "".join(conv(x) for x in line)


if __name__ == "__main__":
    # I know there's a billion better ways to do this but IDGAF.
    def verify(
        text: str,
        meta: ConcatableSequence,
        width: int,
        expectedText: List[str],
        expectedMeta: List[ConcatableSequence],
        *,
        strip_trailing_newlines: bool = True,
        strip_trailing_spaces: bool = True,
    ) -> None:
        output = wordwrap(
            text,
            meta,
            width,
            strip_trailing_newlines=strip_trailing_newlines,
            strip_trailing_spaces=strip_trailing_spaces,
        )
        actualText = [x[0] for x in output]
        actualMeta = [x[1] for x in output]

        assert (
            actualText == expectedText
        ), f"Expected text {expectedText} but got text {actualText}"
        assert (
            actualMeta == expectedMeta
        ), f"Expected meta {expectedMeta} but got meta {actualMeta}"

    # Empty.
    verify("", "", 15, [""], [""])

    # Leading space respect, trailing space strip.
    verify("  test", "123456", 15, ["  test"], ["123456"])
    verify("test  ", "123456", 15, ["test"], ["1234"])

    # Fits within space.
    verify("12345", "abcde", 15, ["12345"], ["abcde"])

    # Handles newlines explicitly.
    verify("123\n45", "abc de", 15, ["123", "45"], ["abc", "de"])
    verify("123\n\n45", "abc  de", 15, ["123", "", "45"], ["abc", "", "de"])

    # Handles leading/trailing space with newlines.
    verify(
        "  test\ntest  ", "123456 123456", 15, ["  test", "test"], ["123456", "1234"]
    )
    verify(
        "test  \n  test", "123456 123456", 15, ["test", "  test"], ["1234", "123456"]
    )

    # Wraps in expected spot.
    verify("123 4567 890", "abc defg hij", 10, ["123 4567", "890"], ["abc defg", "hij"])
    verify(
        "123 4567 890",
        "abc defg hij",
        4,
        ["123", "4567", "890"],
        ["abc", "defg", "hij"],
    )
    verify("123-4567 890", "abc-defg hij", 10, ["123-4567", "890"], ["abc-defg", "hij"])
    verify(
        "123 4567-890", "abc defg-hij", 10, ["123 4567-", "890"], ["abc defg-", "hij"]
    )

    # Handles multi-space elegantly.
    verify(
        "123  4567  890",
        "abc  defg  hij",
        9,
        ["123  4567", "890"],
        ["abc  defg", "hij"],
    )
    verify(
        "123  4567  890",
        "abc  defg  hij",
        10,
        ["123  4567", "890"],
        ["abc  defg", "hij"],
    )

    # Handles newlines and wraps together.
    verify(
        "123 4567\n890", "abc defg hij", 10, ["123 4567", "890"], ["abc defg", "hij"]
    )
    verify(
        "123\n4567 890", "abc defg hij", 10, ["123", "4567 890"], ["abc", "defg hij"]
    )

    # Handles unfortunate word-wrap issues.
    verify("abcdefg", "1234567", 5, ["abcde", "fg"], ["12345", "67"])
    verify(
        "abcdefg hij kl",
        "1234567 123 45",
        6,
        ["abcdef", "g hij", "kl"],
        ["123456", "7 123", "45"],
    )

    # Handles multi newlines and trailing newlines properly.
    verify(
        "a\nb\n\nc\n",
        "1 2  3 ",
        64,
        ["a", "b", "", "c", ""],
        ["1", "2", "", "3", ""],
        strip_trailing_newlines=False,
    )
    verify(
        "a\nb\n\nc\n",
        "1 2  3 ",
        64,
        ["a", "b", "", "c"],
        ["1", "2", "", "3"],
        strip_trailing_newlines=True,
    )

    # Handles stripping trailing spaces properly.
    verify(
        "a     b  ", "1     2  ", 5, ["a", "b"], ["1", "2"], strip_trailing_spaces=True
    )
    verify(
        "a  \n b  ", "1   23  ", 5, ["a", " b"], ["1", "23"], strip_trailing_spaces=True
    )
    verify(
        "abcde f ",
        "12345678",
        5,
        ["abcde", "f"],
        ["12345", "7"],
        strip_trailing_spaces=True,
    )
    verify(
        "abcde ",
        "123456",
        5,
        ["abcde"],
        ["12345"],
        strip_trailing_spaces=True,
    )
    verify(
        "a     b  ",
        "123456789",
        5,
        ["a    ", " b  "],
        ["12345", "6789"],
        strip_trailing_spaces=False,
    )
    verify(
        "abcde f ",
        "12345678",
        5,
        ["abcde", "f "],
        ["12345", "78"],
        strip_trailing_spaces=False,
    )
    verify(
        "abcde ",
        "123456",
        5,
        ["abcde"],
        ["12345"],
        strip_trailing_spaces=False,
        strip_trailing_newlines=True,
    )
    verify(
        "abcde ",
        "123456",
        5,
        ["abcde", ""],
        ["12345", ""],
        strip_trailing_spaces=False,
        strip_trailing_newlines=False,
    )

    # Hey we did it!
    print("Passed", file=sys.stderr)
