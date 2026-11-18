"""Compatibility and coordination utilities for TextEncode text processing.

This module deliberately remains small. Parsing belongs in parser.py;
linguistic tokenisation belongs in linguistics.py; descriptive analysis belongs
in text_analysis.py. Existing imports from processor.py remain supported.
"""
from __future__ import annotations

from collections import Counter
import re

try:
    from modules.linguistics import tokenize
except ImportError:  # pragma: no cover
    from linguistics_revised import tokenize

_TERMINATOR_RE = re.compile(r'[।.!?]+')


def normalise_token(token: str) -> str:
    """Legacy helper retained for backwards compatibility."""
    try:
        from modules.linguistics import normalise_token as _normalise
    except ImportError:  # pragma: no cover
        from linguistics_revised import normalise_token as _normalise
    return _normalise(token)


def count_words(text: str) -> int:
    return len(tokenize(text))


def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    counter = Counter(tokenize(text))
    return counter.most_common() if limit is None else counter.most_common(max(0, limit))


def count_sentences(text: str) -> int:
    return sum(1 for piece in _TERMINATOR_RE.split(text) if any(ch.isalnum() for ch in piece))


def analysable_text(passages) -> str:
    """Join readable passage text, excluding code blocks."""
    return '\n\n'.join(
        p.get('plain_text', '') for p in passages
        if p.get('passage_type') != 'code_block' and p.get('plain_text')
    )


def document_statistics(source_text: str, passages) -> dict:
    body = analysable_text(passages)
    words = tokenize(body)
    by_type = Counter(p.get('passage_type', 'unknown') for p in passages)
    return {
        'char_count': len(source_text),
        'char_count_no_whitespace': sum(not ch.isspace() for ch in source_text),
        'word_count': len(words),
        'unique_word_count': len(set(words)),
        'sentence_count': count_sentences(body),
        'passage_count': len(passages),
        'heading_count': by_type.get('heading', 0),
        'paragraph_count': by_type.get('paragraph', 0),
        'list_item_count': by_type.get('list_item', 0),
        'blockquote_count': by_type.get('blockquote', 0),
        'code_block_count': by_type.get('code_block', 0),
    }


def _snippet(text: str, start: int, end: int, context: int) -> str:
    left = max(0, start - context)
    right = min(len(text), end + context)
    return ('…' if left else '') + text[left:right].replace('\n', ' ') + ('…' if right < len(text) else '')


def search_passages(passages, query: str, case_sensitive: bool = False,
                    context_chars: int = 60, max_snippets: int = 3) -> list[dict]:
    """Search passage plain text and return match offsets local to plain_text."""
    if not isinstance(query, str) or not query.strip():
        return []
    if context_chars < 0 or max_snippets < 0:
        raise ValueError('context_chars and max_snippets must be >= 0')
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    results = []
    for passage in passages:
        text = passage.get('plain_text', '')
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        results.append({
            'doc_id': passage.get('doc_id'),
            'passage_id': passage.get('passage_id'),
            'sequence': passage.get('sequence'),
            'passage_type': passage.get('passage_type'),
            'heading_path': passage.get('heading_path') or '',
            'match_count': len(matches),
            'matches': [{'start': m.start(), 'end': m.end(), 'text': m.group(0)} for m in matches],
            'snippets': [_snippet(text, m.start(), m.end(), context_chars) for m in matches[:max_snippets]],
        })
    return results
