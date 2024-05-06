from .text import ControlCodes, highlight, sanitize

from typing import List, Sequence, Tuple, Union


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


def replace(
    original: Tuple[str, Sequence[ControlCodes]],
    replacement: Union[str, Tuple[str, Sequence[ControlCodes]]],
    offset: int = 0,
) -> Tuple[str, List[ControlCodes]]:
    # First, grab the text and codes we're replacing.
    originalText, originalCodes = original

    # Now, figure out if the replacement is just text or a tuple.
    if isinstance(replacement, str):
        text = replacement
        codes = None
    else:
        text, codes = replacement

    # Now, bounds check the replacement.
    if offset >= 0:
        # Offset is positive, from the left.
        if (offset + len(text)) > len(originalText):
            amount = len(originalText) - offset
            text = text[:amount]
            if codes is not None:
                codes = codes[:amount]
    else:
        # Offset is negative, from the right.
        offset = (len(originalText) - len(text)) + offset
        if offset < 0:
            text = text[(-offset):]
            if codes is not None:
                codes = codes[(-offset):]
            offset = 0

    # Now, insert just the text, or the text and codes.
    if codes is None:
        return (
            originalText[:offset] + text + originalText[(offset + len(text)) :],
            list(originalCodes),
        )
    else:
        return (
            originalText[:offset] + text + originalText[(offset + len(text)) :],
            [*originalCodes[:offset], *codes, *originalCodes[(offset + len(codes)) :]],
        )


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
