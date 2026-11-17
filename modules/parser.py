"""Markdown parser for TextEncode."""

import hashlib
from markdown_it import MarkdownIt

PASSAGE_TYPES = ("heading", "paragraph", "list_item", "blockquote", "code_block")
_MD = MarkdownIt("commonmark")

def _sanitize_source(source: str) -> str:
    source = source.replace("\x00", "")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    return source

def _line_starts(source: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            starts.append(index + 1)
    if starts[-1] != len(source):
        starts.append(len(source))
    return starts

def _inline_after(tokens: list, index: int):
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None

def _inline_plain_text(inline) -> str:
    if inline is None: return ""
    if not inline.children: return inline.content
    parts = []
    for child in inline.children:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)

def _make_passage(source, line_starts, line_map, passage_type, plain_text, sequence, heading_stack, heading_level):
    start_line, end_line = line_map
    last_line = len(line_starts) - 1
    start_line = max(0, min(start_line, last_line))
    end_line = max(start_line, min(end_line, last_line))
    char_start = line_starts[start_line]
    char_end = line_starts[end_line]
    while char_end > char_start and source[char_end - 1] in "\r\n":
        char_end -= 1
    text = source[char_start:char_end]
    clean = (plain_text or "").strip() or text.strip()
    return {
        "sequence": sequence,
        "passage_type": passage_type,
        "heading_level": heading_level,
        "heading_path": " > ".join(title for _, title in heading_stack),
        "text": text,
        "plain_text": clean,
        "char_start": char_start,
        "char_end": char_end,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }

def parse_markdown(source: str) -> list[dict]:
    if not source: return []
    source = _sanitize_source(source)
    tokens = _MD.parse(source)
    starts = _line_starts(source)
    passages = []
    heading_stack = []
    list_depth = 0
    quote_depth = 0

    for index, token in enumerate(tokens):
        if token.type in ("bullet_list_open", "ordered_list_open"): list_depth += 1
        elif token.type in ("bullet_list_close", "ordered_list_close"): list_depth = max(0, list_depth - 1)
        elif token.type == "blockquote_open": quote_depth += 1
        elif token.type == "blockquote_close": quote_depth = max(0, quote_depth - 1)
        elif token.type == "heading_open":
            level = int(token.tag[1])
            inline = _inline_after(tokens, index)
            title = _inline_plain_text(inline).strip()
            while heading_stack and heading_stack[-1][0] >= level: heading_stack.pop()
            heading_stack.append((level, title))
            passages.append(_make_passage(source, starts, token.map, "heading", title, len(passages) + 1, heading_stack, level))
        elif token.type == "paragraph_open":
            inline = _inline_after(tokens, index)
            text = _inline_plain_text(inline)
            if list_depth > 0: passage_type = "list_item"
            elif quote_depth > 0: passage_type = "blockquote"
            else: passage_type = "paragraph"
            passages.append(_make_passage(source, starts, token.map, passage_type, text, len(passages) + 1, heading_stack, None))
        elif token.type == "fence":
            passages.append(_make_passage(source, starts, token.map, "code_block", token.content, len(passages) + 1, heading_stack, None))
    return passages

def guess_title(passages: list[dict]) -> str | None:
    for p in passages:
        if p["passage_type"] == "heading" and p["heading_level"] == 1 and p["plain_text"]:
            return p["plain_text"]
    for p in passages:
        if p["passage_type"] == "heading" and p["plain_text"]:
            return p["plain_text"]
    return None
