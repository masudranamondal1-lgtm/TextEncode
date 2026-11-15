"""Text statistics and keyword search for TextEncode."""

from __future__ import annotations
import re
from collections import Counter
from modules import linguistics

_TERMINATOR_RE = re.compile(r"[।.!?]+")

def count_sentences(text: str) -> int:
    return sum(
        1 for piece in _TERMINATOR_RE.split(text)
        if any(char.isalnum() for char in piece)
    )

def analysable_text(passages) -> str:
    return "\n\n".join(
        p["plain_text"] for p in passages if p["passage_type"] != "code_block"
    )

def document_statistics(source_text: str, passages) -> dict:
    body = analysable_text(passages)
    words = linguistics.tokenize(body)
    by_type = Counter(p["passage_type"] for p in passages)
    return {
        "char_count": len(source_text),
        "char_count_no_whitespace": sum(1 for ch in source_text if not ch.isspace()),
        "word_count": len(words),
        "unique_word_count": len(set(words)),
        "sentence_count": count_sentences(body),
        "passage_count": len(passages),
        "heading_count": by_type.get("heading", 0),
        "paragraph_count": by_type.get("paragraph", 0),
        "list_item_count": by_type.get("list_item", 0),
        "blockquote_count": by_type.get("blockquote", 0),
        "code_block_count": by_type.get("code_block", 0),
    }

def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    return linguistics.word_frequencies(text, limit=limit)

def search_passages(passages, query: str, case_sensitive: bool = False,
                    context_chars: int = 60, max_snippets: int = 3) -> list[dict]:
    if not query or not query.strip():
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)
    results = []
    for passage in passages:
        text = passage["plain_text"]
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        results.append({
            "doc_id": passage["doc_id"],
            "passage_id": passage["passage_id"],
            "sequence": passage["sequence"],
            "passage_type": passage["passage_type"],
            "heading_path": passage.get("heading_path") or "",
            "match_count": len(matches),
            "snippets": [
                text[max(0, m.start() - context_chars):min(len(text), m.end() + context_chars)].replace("\n", " ")
                for m in matches[:max_snippets]
            ],
        })
    return results