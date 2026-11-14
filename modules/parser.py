"""Markdown parsing for TextEncode.

Turns a Markdown source string into an ordered list of *passages*: headings,
paragraphs, list items, block-quote paragraphs and fenced code blocks.

Two design decisions matter:

1. markdown-it-py is used only to decide *which lines* form which structural
   unit (``Token.map`` is a half-open range of line numbers). The passage text
   and character offsets are then sliced directly out of the ORIGINAL source,
   so this invariant holds for every passage:

       source[char_start:char_end] == text

   Nothing is normalised, re-wrapped or reformatted: the original text is
   preserved byte-for-byte inside the stored source string.

2. Offsets are Python string indices, i.e. offsets counted in Unicode code
   points (not bytes, not grapheme clusters). This is the only convention that
   can be recomputed identically on any platform from the stored source text.

Known limits (deliberate, MVP): CommonMark only (no GFM tables), HTML blocks
and thematic breaks are ignored, and a bare carriage return (old Mac line
ending) is rejected rather than silently misaligned.
"""

from __future__ import annotations

import hashlib

from markdown_it import MarkdownIt

#: Passage types produced by this parser. Must match the CHECK constraint
#: on ``passages.passage_type`` in database/db.py.
PASSAGE_TYPES = ("heading", "paragraph", "list_item", "blockquote", "code_block")

_MD = MarkdownIt("commonmark")


def _check_line_endings(source: str) -> None:
    """Reject bare CR line endings, which would desynchronise line numbers."""
    if "\r" in source.replace("\r\n", ""):
        raise ValueError(
            "This file contains bare carriage-return (\\r) line endings, which "
            "are not supported. Please re-save it with Windows (CRLF) or "
            "Unix (LF) line endings."
        )


def _line_starts(source: str) -> list[int]:
    """Return the character offset at which each line begins.

    A sentinel entry equal to ``len(source)`` is appended (when needed) so the
    end of line ``i`` can be read as ``starts[i + 1]``. Only ``\\n`` is treated
    as a line separator, matching markdown-it-py's normalised line counting.
    """
    starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            starts.append(index + 1)
    if starts[-1] != len(source):
        starts.append(len(source))
    return starts


def _inline_after(tokens: list, index: int):
    """Return the ``inline`` token that follows a block-open token, if any."""
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _inline_plain_text(inline) -> str:
    """Flatten an inline token to readable prose (markers removed).

    ``inline.content`` still contains Markdown markers such as ``*`` or ``**``.
    For word counts and keyword search we want clean prose, so we concatenate
    the text/code children instead.
    """
    if inline is None:
        return ""
    if not inline.children:
        return inline.content
    parts = []
    for child in inline.children:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)


def _make_passage(source, line_starts, line_map, passage_type, plain_text,
                  sequence, heading_stack, heading_level):
    """Build one passage dict from a token line range."""
    start_line, end_line = line_map
    last_line = len(line_starts) - 1
    start_line = max(0, min(start_line, last_line))
    end_line = max(start_line, min(end_line, last_line))

    char_start = line_starts[start_line]
    char_end = line_starts[end_line]
    # Drop trailing line-ending characters so the passage text is clean.
    while char_end > char_start and source[char_end - 1] in "\r\n":
        char_end -= 1

    text = source[char_start:char_end]
    clean = (plain_text or "").strip() or text.strip()

    return {
        "sequence": sequence,
        "passage_type": passage_type,
        "heading_level": heading_level,
        "heading_path": " > ".join(title for _, title in heading_stack),
        "text": text,                 # raw source slice
        "plain_text": clean,          # readable prose for stats/search
        "char_start": char_start,
        "char_end": char_end,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def parse_markdown(source: str) -> list[dict]:
    """Parse *source* into an ordered list of passage dicts.

    Raises ``ValueError`` for source with unsupported line endings.
    Returns an empty list for empty input.
    """
    if not source:
        return []

    _check_line_endings(source)
    tokens = _MD.parse(source)
    starts = _line_starts(source)

    passages: list[dict] = []
    heading_stack: list[tuple[int, str]] = []
    list_depth = 0
    quote_depth = 0

    for index, token in enumerate(tokens):
        if token.type in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            list_depth = max(0, list_depth - 1)
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)

        elif token.type == "heading_open":
            level = int(token.tag[1])
            inline = _inline_after(tokens, index)
            title = _inline_plain_text(inline).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            passages.append(_make_passage(
                source, starts, token.map, "heading", title,
                len(passages) + 1, heading_stack, level,
            ))

        elif token.type == "paragraph_open":
            inline = _inline_after(tokens, index)
            text = _inline_plain_text(inline)
            if list_depth > 0:
                passage_type = "list_item"
            elif quote_depth > 0:
                passage_type = "blockquote"
            else:
                passage_type = "paragraph"
            passages.append(_make_passage(
                source, starts, token.map, passage_type, text,
                len(passages) + 1, heading_stack, None,
            ))

        elif token.type == "fence":
            passages.append(_make_passage(
                source, starts, token.map, "code_block", token.content,
                len(passages) + 1, heading_stack, None,
            ))

    return passages


def guess_title(passages: list[dict]) -> str | None:
    """Suggest a document title: first level-1 heading, else first heading."""
    for passage in passages:
        if (passage["passage_type"] == "heading"
                and passage["heading_level"] == 1
                and passage["plain_text"]):
            return passage["plain_text"]
    for passage in passages:
        if passage["passage_type"] == "heading" and passage["plain_text"]:
            return passage["plain_text"]
    return None
