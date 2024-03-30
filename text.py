from clip import BoundingRectangle
from vtpy import Terminal
from typing import List, Sequence, Tuple, TypeVar


class ControlCodes:
    def __init__(self, *, bold: bool = False, underline: bool = False, reverse: bool = False) -> None:
        self.bold = bold
        self.underline = underline
        self.reverse = reverse

    def codesFrom(self, prev: "ControlCodes") -> List[bytes]:
        if ((not self.bold) and prev.bold) or ((not self.underline) and prev.underline) or ((not self.reverse) and prev.reverse):
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


TObj = TypeVar("TObj", bound=object)


def wordwrap(text: str, meta: Sequence[TObj], width: int) -> List[Tuple[str, Sequence[TObj]]]:
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

    outLines: List[Tuple[str, Sequence[TObj]]] = []

    # We don't handle non-unix line endings, so convert them.
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # First, go through and find any potential wrap points.
    wrapPoints: List[int] = []
    lastPunctuation = False

    for i, ch in enumerate(text):
        if ch in {" ", "\t", "\n"}:
            lastPunctuation = False
            wrapPoints.append(i)
        elif ch in {"-", "+", ";", "~", "(", ")", "[", "]", "{", "}", "<", ">"}:
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
                text = text[(pos + 1):]
                meta = meta[(pos + 1):]

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

            if text[pos] in {" ", "\t"}:
                # We don't include the space at the end of the line, or in the
                # beginning of the next, so drop it.
                outLines.append((text[:pos], meta[:pos]))

                # Find the first non-space to wrap
                spot = -1
                for i in range(pos + 1, len(text)):
                    if text[i] not in {" ", "\t"}:
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
                    meta = []
                    wrapPoints = []
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

    # Finally, get rid of leading and trailing whitespace.
    def stripSpace(line: Tuple[str, Sequence[TObj]]) -> Tuple[str, Sequence[TObj]]:
        text, meta = line

        while text and text[0] in {" "}:
            text = text[1:]
            meta = meta[1:]

        while text and text[-1] in {" "}:
            text = text[:-1]
            meta = meta[:-1]

        return (text, meta)

    return [stripSpace(line) for line in outLines]


def display(terminal: Terminal, lines: List[Tuple[str, List[ControlCodes]]], bounds: BoundingRectangle) -> None:
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
    bounds = bounds.clip(BoundingRectangle(left=1, top=1, right=terminal.columns + 1, bottom=terminal.rows + 1))
    if bounds.width == 0 or bounds.height == 0:
        return

    # Clip off any lines that go off the bottom of the screen.
    lines = lines[:bounds.height]

    # Now, figure out where we left off last time we drew anything.
    last = ControlCodes(bold=terminal.bolded, underline=terminal.underlined, reverse=terminal.reversed)

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
        text = text[:bounds.width]
        codes = codes[:bounds.width]

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


if __name__ == "__main__":
    # I know there's a billion better ways to do this but IDGAF.
    def verify(text: str, meta: Sequence[object], width: int, expectedText: List[str], expectedMeta: List[Sequence[object]]) -> None:
        output = wordwrap(text, meta, width)
        actualText = [x[0] for x in output]
        actualMeta = [x[1] for x in output]

        assert actualText == expectedText, f"Expected {expectedText} but got {actualText}"
        assert actualMeta == expectedMeta, f"Expected {expectedMeta} but got {actualMeta}"

    # Empty.
    verify("", "", 15, [""], [""])

    # Fits within space.
    verify("12345", "abcde", 15, ["12345"], ["abcde"])

    # Handles newlines explicitly.
    verify("123\n45", "abc de", 15, ["123", "45"], ["abc", "de"])
    verify("123\n\n45", "abc  de", 15, ["123", "", "45"], ["abc", "", "de"])

    # Wraps in expected spot.
    verify("123 4567 890", "abc defg hij", 10, ["123 4567", "890"], ["abc defg", "hij"])
    verify("123 4567 890", "abc defg hij", 4, ["123", "4567", "890"], ["abc", "defg", "hij"])
    verify("123-4567 890", "abc-defg hij", 10, ["123-4567", "890"], ["abc-defg", "hij"])
    verify("123 4567-890", "abc defg-hij", 10, ["123 4567-", "890"], ["abc defg-", "hij"])

    # Handles multi-space elegantly.
    verify("123  4567  890", "abc  defg  hij", 9, ["123  4567", "890"], ["abc  defg", "hij"])
    verify("123  4567  890", "abc  defg  hij", 10, ["123  4567", "890"], ["abc  defg", "hij"])

    # Handles newlines and wraps together.
    verify("123 4567\n890", "abc defg hij", 10, ["123 4567", "890"], ["abc defg", "hij"])
    verify("123\n4567 890", "abc defg hij", 10, ["123", "4567 890"], ["abc", "defg hij"])

    # Handles unfortunate word-wrap issues.
    verify("abcdefg", "1234567", 5, ["abcde", "fg"], ["12345", "67"])
    verify("abcdefg hij kl", "1234567 123 45", 6, ["abcdef", "g hij", "kl"], ["123456", "7 123", "45"])

    # Hey we did it!
    print("Passed")
