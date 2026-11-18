"""Text analysis for TextEncode: statistics, frequency, n-grams and KWIC.

All offsets returned by KWIC are Python Unicode code-point offsets into the
exact input string. Token counts are computational estimates, not linguistic
claims. Original text is never modified.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Iterable

try:  # Works both inside the application package and in isolated tests.
    from modules.linguistics import tokenize, tokenize_with_offsets, filter_stopwords
except ImportError:  # pragma: no cover - direct-module fallback
    from linguistics_revised import tokenize, tokenize_with_offsets, filter_stopwords

_SENTENCE_SPLIT_RE = re.compile(r'[।.!?]+')


def _validate_limit(limit: int | None, name: str = 'limit') -> None:
    if limit is not None and limit < 0:
        raise ValueError(f'{name} must be >= 0 or None')


def get_basic_stats(text: str) -> dict:
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    tokens = tokenize(text)
    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
    count = len(sentences)
    return {
        'word_count': len(tokens),
        'unique_words': len(set(tokens)),
        'char_count': len(text),
        'char_count_no_whitespace': sum(not char.isspace() for char in text),
        'sentence_count': count,
        'avg_sentence_length': round(len(tokens) / count, 2) if count else 0,
    }


def get_word_frequency(text: str, limit: int = 50, min_length: int = 1) -> list[tuple[str, int]]:
    _validate_limit(limit)
    if min_length < 1:
        raise ValueError('min_length must be >= 1')
    tokens = [t for t in tokenize(text) if len(t) >= min_length]
    return Counter(tokens).most_common(limit)


def get_ngrams(text: str, n: int = 2, limit: int = 50) -> list[tuple[str, int]]:
    _validate_limit(limit)
    if n < 1:
        raise ValueError('n must be >= 1')
    tokens = tokenize(text)
    if len(tokens) < n or limit == 0:
        return []
    grams = (' '.join(tokens[i:i+n]) for i in range(len(tokens) - n + 1))
    return Counter(grams).most_common(limit)


def get_kwic(text: str, query: str, window: int = 40, limit: int = 100,
             case_sensitive: bool = False) -> list[dict]:
    """Return exact substring matches with source offsets and context."""
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    if not isinstance(query, str) or not query.strip():
        return []
    if window < 0:
        raise ValueError('window must be >= 0')
    _validate_limit(limit)
    if limit == 0:
        return []
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    results = []
    for match in pattern.finditer(text):
        start, end = match.span()
        left_start = max(0, start - window)
        right_end = min(len(text), end + window)
        results.append({
            'match': text[start:end],
            'left': ('…' if left_start else '') + text[left_start:start].replace('\n', ' '),
            'right': text[end:right_end].replace('\n', ' ') + ('…' if right_end < len(text) else ''),
            'start': start,
            'end': end,
            'context_start': left_start,
            'context_end': right_end,
        })
        if len(results) >= limit:
            break
    return results


def get_kwic_tokens(text: str, query: str, window_tokens: int = 5, limit: int = 100) -> list[dict]:
    """Token-oriented concordance with token offsets; query is matched literally."""
    if window_tokens < 0:
        raise ValueError('window_tokens must be >= 0')
    _validate_limit(limit)
    if not query or not query.strip() or limit == 0:
        return []
    tokens = tokenize_with_offsets(text)
    target = query.casefold()
    results = []
    for i, token in enumerate(tokens):
        if token.normalised != target:
            continue
        left_i = max(0, i - window_tokens)
        right_i = min(len(tokens), i + window_tokens + 1)
        results.append({
            'match': token.surface, 'start': token.start, 'end': token.end,
            'left': ' '.join(t.surface for t in tokens[left_i:i]),
            'right': ' '.join(t.surface for t in tokens[i+1:right_i]),
            'token_index': i,
        })
        if len(results) >= limit:
            break
    return results


def get_filtered_word_frequency(text: str, limit: int = 50, remove_stopwords: bool = False) -> list[tuple[str, int]]:
    _validate_limit(limit)
    tokens = tokenize(text)
    if remove_stopwords:
        tokens = filter_stopwords(tokens)
    return Counter(tokens).most_common(limit)
