"""Markdown parser for TextEncode.

The parser keeps source offsets relative to the exact string supplied by the
caller. In particular, it must not normalise line endings or remove characters
before calculating offsets: mentions and evidence records use these offsets to
refer back to the stored source text.
"""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any

from markdown_it import MarkdownIt


PASSAGE_TYPES = ("heading", "paragraph", "list_item", "blockquote", "code_block")
_MD = MarkdownIt("commonmark")
_HTML_TAG_RE = re.compile(r"<[^>]*>")


def _line_starts(source: str) -> list[int]:
    """Return character offsets for the beginning of each source line."""
    starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            starts.append(index + 1)
    # markdown-it's line maps use an exclusive end line. A final offset is
    # needed for the last line when the source has no trailing newline.
    if starts[-1] != len(source):
        starts.append(len(source))
    return starts


def _inline_after(tokens: list[Any], index: int) -> Any | None:
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _inline_plain_text(inline: Any | None) -> str:
    """Extract readable inline text without Markdown formatting syntax."""
    if inline is None:
        return ""

    children = inline.children or []
    if not children:
        return inline.content or ""

    parts: list[str] = []
    for child in children:
        token_type = child.type
        if token_type in ("text", "code_inline"):
            parts.append(child.content)
        elif token_type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif token_type == "image":
            # markdown-it stores image alt text in token.content.
            if child.content:
                parts.append(child.content)
        elif token_type == "html_inline":
            # Keep readable text from inline HTML, but not the tag syntax.
            parts.append(_HTML_TAG_RE.sub("", child.content or ""))
        # Formatting tokens (em_open, strong_close, etc.) carry no text.
    return html.unescape("".join(parts))


def _make_passage(
    source: str,
    line_starts: list[int],
    line_map: list[int] | tuple[int, int],
    passage_type: str,
    plain_text: str,
    sequence: int,
    heading_stack: list[tuple[int, str]],
    heading_level: int | None,
) -> dict[str, Any]:
    start_line, end_line = line_map
    last_line = len(line_starts) - 1
    start_line = max(0, min(int(start_line), last_line))
    end_line = max(start_line, min(int(end_line), last_line))

    char_start = line_starts[start_line]
    char_end = line_starts[end_line]

    # Exclude only the line terminator at the end of the block. Do not strip
    # leading/trailing spaces from the source slice: offsets must remain exact.
    while char_end > char_start and source[char_end - 1] in "\r\n":
        char_end -= 1

    source_text = source[char_start:char_end]
    clean_text = (plain_text or "").strip()
    if not clean_text:
        clean_text = source_text.strip()

    return {
        "sequence": sequence,
        "passage_type": passage_type,
        "heading_level": heading_level,
        "heading_path": " > ".join(title for _, title in heading_stack),
        "text": source_text,
        "plain_text": clean_text,
        "char_start": char_start,
        "char_end": char_end,
        "content_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
    }


def parse_markdown(source: str) -> list[dict[str, Any]]:
    """Parse Markdown into source-addressable passages.

    Offsets are Python string (Unicode code-point) offsets into the exact
    ``source`` argument. They are not byte offsets or grapheme-cluster offsets.
    """
    if source is None or source == "":
        return []
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if "\x00" in source:
        raise ValueError("source contains a NUL character; clean or repair the input before parsing")
    # markdown-it uses LF and CRLF line boundaries. A bare CR is ambiguous
    # for line maps, so reject it instead of silently changing source offsets.
    if any(source[i] == "\r" and (i + 1 >= len(source) or source[i + 1] != "\n")
           for i in range(len(source))):
        raise ValueError("bare carriage return found; use LF or CRLF line endings")

    tokens = _MD.parse(source)
    starts = _line_starts(source)
    passages: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []
    list_depth = 0
    quote_depth = 0

    for index, token in enumerate(tokens):
        token_type = token.type

        if token_type in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif token_type in ("bullet_list_close", "ordered_list_close"):
            list_depth = max(0, list_depth - 1)
        elif token_type == "blockquote_open":
            quote_depth += 1
        elif token_type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)

        elif token_type == "heading_open":
            level = int(token.tag[1])
            inline = _inline_after(tokens, index)
            title = _inline_plain_text(inline).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            if token.map:
                passages.append(
                    _make_passage(
                        source, starts, token.map, "heading", title,
                        len(passages) + 1, heading_stack, level,
                    )
                )

        elif token_type == "paragraph_open":
            inline = _inline_after(tokens, index)
            text = _inline_plain_text(inline)
            if list_depth:
                passage_type = "list_item"
            elif quote_depth:
                passage_type = "blockquote"
            else:
                passage_type = "paragraph"

            if token.map:
                passages.append(
                    _make_passage(
                        source, starts, token.map, passage_type, text,
                        len(passages) + 1, heading_stack, None,
                    )
                )

        elif token_type in ("fence", "code_block"):
            if token.map:
                passages.append(
                    _make_passage(
                        source, starts, token.map, "code_block", token.content,
                        len(passages) + 1, heading_stack, None,
                    )
                )

    return passages


def guess_title(passages: list[dict[str, Any]]) -> str | None:
    """Return the first H1 title, or the first available heading."""
    for passage in passages:
        if (
            passage.get("passage_type") == "heading"
            and passage.get("heading_level") == 1
            and passage.get("plain_text")
        ):
            return passage["plain_text"]

    for passage in passages:
        if passage.get("passage_type") == "heading" and passage.get("plain_text"):
            return passage["plain_text"]

    return None
