"""Text statistics and keyword search for TextEncode.

IMPORTANT, DOCUMENTED LIMITATIONS
---------------------------------
* Words are counted by splitting on whitespace and trimming punctuation from
  the edges of each token. This is NOT a linguistic tokeniser. Bengali
  compounds, sandhi forms, enclitics and punctuation conventions mean the
  counts are approximate and are comparable only within this application.

* We deliberately avoid the regex ``\\w+``. In Python, ``\\w`` matches
  ``str.isalnum()``, which is False for Indic spacing combining marks
  (Unicode category Mc) such as ি (U+09BF) and ী (U+09C0). ``\\w+`` would split
  ইছামতী into ইছ + মত. See test_processor.test_tokenize_keeps_bengali_marks.

* Sentences are split on । . ! ? Abbreviations ("Dr."), decimals and Bengali
  abbreviations will cause occasional over-counting.

Nothing here modifies the stored text.
"""

from __future__ import annotations

import re
from collections import Counter

#: Characters stripped from the beginning/end of a whitespace token.
_EDGE_PUNCTUATION = "।॥.,;:!?\"'“”‘’«»()[]{}<>—–-…*_`~|/\\+=#"

#: Sentence terminators for both Bengali and Latin scripts.
_TERMINATOR_RE = re.compile(r"[।.!?]+")


def normalise_token(token: str) -> str:
    """Trim edge punctuation from a whitespace token and case-fold it."""
    return token.strip(_EDGE_PUNCTUATION).casefold()


def tokenize(text: str) -> list[str]:
    """Return normalised word tokens. See module docstring for limits."""
    tokens = []
    for raw in text.split():
        token = normalise_token(raw)
        if token:
            tokens.append(token)
    return tokens


def count_words(text: str) -> int:
    """Approximate word count (whitespace based)."""
    return len(tokenize(text))


def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    """Return ``[(token, count), ...]`` sorted by descending count."""
    counter = Counter(tokenize(text))
    return counter.most_common() if limit is None else counter.most_common(limit)


def count_sentences(text: str) -> int:
    """Approximate sentence count using । . ! ? as terminators."""
    return sum(
        1 for piece in _TERMINATOR_RE.split(text)
        if any(char.isalnum() for char in piece)
    )


def analysable_text(passages) -> str:
    """Join the readable text of all passages, skipping code blocks."""
    return "\n\n".join(
        p["plain_text"] for p in passages if p["passage_type"] != "code_block"
    )


def document_statistics(source_text: str, passages) -> dict:
    """Compute live statistics for one document. Nothing is cached or stored."""
    body = analysable_text(passages)
    words = tokenize(body)
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


def _snippet(text: str, start: int, end: int, context: int) -> str:
    """Return a short context window around a match."""
    left = max(0, start - context)
    right = min(len(text), end + context)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return prefix + text[left:right].replace("\n", " ") + suffix


def search_passages(passages, query: str, case_sensitive: bool = False,
                    context_chars: int = 60, max_snippets: int = 3) -> list[dict]:
    """Find *query* in passage plain text.

    Case-insensitive search uses ``re.IGNORECASE`` rather than ``str.casefold``
    on purpose: casefold can change string length for some characters, which
    would make match offsets invalid inside the original passage text.

    Returns one dict per matching passage, with ``snippets`` for display.
    """
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
                _snippet(text, m.start(), m.end(), context_chars)
                for m in matches[:max_snippets]
            ],
        })
    return results
