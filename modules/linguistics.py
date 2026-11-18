"""Unicode-aware linguistic utilities for TextEncode.

This is a lightweight, deterministic layer, not a full Bengali morphological
analyser. Surface text is never rewritten. Token offsets refer to the exact
Python string supplied by the caller (Unicode code-point offsets).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import unicodedata
from typing import Iterable

# Keep the legacy name for code that imports it, but tokenisation itself uses
# Unicode categories rather than a Bengali-only regular expression.
STOP_WORDS = {
    'আর', 'কি', 'কে', 'যে', 'যা', 'এই', 'সেই', 'এ', 'ও', 'না', 'হয়', 'থাক',
    'তবু', 'তার', 'করে', 'করা', 'হলো', 'হল', 'নেই', 'আরও', 'কিন্তু', 'এখন',
    'এক', 'একটি', 'সব', 'মনে', 'মতো', 'হয়ে', 'যায়', 'গেছে', 'ছিল', 'আমি',
    'তুমি', 'এবং', 'তাই', 'তবে', 'সে', 'ওই', 'হয়েছে', 'হবে', 'হয়েই',
    'হচ্ছে', 'তোমার', 'আমার', 'যেন', 'কেন', 'কারণ', 'কোনও', 'একা', 'আবার',
    'অনেক', 'সেখানে', 'এখানে',
}

# Explicitly heuristic. These are suggestions, never authoritative lemmas.
BENGALI_SUFFIXES = (
    'গুলির', 'গুলোতে', 'গুলিতে', 'গুলোকে', 'গুলোর', 'গুলি', 'গুলো',
    'দের', 'কে', 'তে', 'রে', 'ের', 'টি', 'টা', 'রা', 'র',
)

_EDGE_PUNCTUATION = "।॥.,;:!?\"'“”‘’«»()[]{}<>—–-…*_`~|/\\+=#"


def _is_word_char(char: str) -> bool:
    """Letters, combining marks and numbers are token characters."""
    category = unicodedata.category(char)
    return category[0] in {'L', 'M', 'N'}


def _is_bengali_char(char: str) -> bool:
    return '\u0980' <= char <= '\u09ff'


@dataclass(frozen=True)
class Token:
    surface: str
    normalised: str
    start: int
    end: int
    token_type: str

    def to_dict(self) -> dict:
        return asdict(self)


def tokenize_with_offsets(text: str, *, include_numbers: bool = True) -> list[Token]:
    """Tokenise text while preserving exact source offsets.

    A token is a contiguous run of Unicode letters/marks/numbers. Combining
    marks remain attached to their base letters, including Bengali vowel signs.
    Apostrophes and hyphens are treated as separators in this first version.
    """
    if not isinstance(text, str) or not text:
        return []
    output: list[Token] = []
    start: int | None = None
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        # Combining marks belong to a preceding token; an isolated mark is
        # not treated as a lexical token.
        valid = category[0] in {'L', 'N'} or (category[0] == 'M' and start is not None)
        if not include_numbers and category.startswith('N'):
            valid = False
        if valid and start is None:
            start = index
        elif not valid and start is not None:
            surface = text[start:index]
            output.append(_make_token(surface, start, index))
            start = None
    if start is not None:
        surface = text[start:]
        output.append(_make_token(surface, start, len(text)))
    return output


def _make_token(surface: str, start: int, end: int) -> Token:
    # NFC is used only for the analytical form. Offsets and surface remain
    # tied to the original, unnormalised source string.
    normalised = unicodedata.normalize('NFC', surface).casefold()
    if all(unicodedata.category(c).startswith('N') for c in surface):
        token_type = 'number'
    elif any(_is_bengali_char(c) for c in surface):
        token_type = 'bengali_word'
    elif any(unicodedata.category(c).startswith('L') for c in surface):
        token_type = 'word'
    else:
        token_type = 'number'
    return Token(surface, normalised, start, end, token_type)


def tokenize(text: str, *, include_numbers: bool = True) -> list[str]:
    """Return normalised lexical tokens; punctuation is excluded."""
    return [t.normalised for t in tokenize_with_offsets(text, include_numbers=include_numbers)]


def normalise_token(token: str) -> str:
    """Normalise one token without changing any stored source text."""
    return unicodedata.normalize('NFC', token.strip(_EDGE_PUNCTUATION)).casefold()


def get_lemma(token: str) -> str:
    """Return a conservative suffix-stripping *suggestion*, not a true lemma.

    The function is retained for compatibility. Researchers should treat its
    output as a candidate and verify it before using it in interpretation.
    """
    if not token:
        return token
    value = unicodedata.normalize('NFC', token).casefold()
    if not any(_is_bengali_char(c) for c in value):
        return value
    for suffix in BENGALI_SUFFIXES:
        if value.endswith(suffix):
            stem = value[:-len(suffix)]
            # Avoid tiny or empty stems. This is only a guard, not morphology.
            bengali_letters = sum(1 for c in stem if _is_bengali_char(c) and unicodedata.category(c).startswith('L'))
            if bengali_letters >= 2:
                return stem
    return value


def lemma_suggestion(token: str) -> dict:
    """Return an explicit, reviewable lemma suggestion record."""
    normalised = normalise_token(token)
    suggestion = get_lemma(normalised)
    return {
        'surface': token,
        'normalised': normalised,
        'suggested_lemma': suggestion,
        'method': 'heuristic_suffix_stripping' if suggestion != normalised else 'identity',
        'review_status': 'unreviewed',
        'is_heuristic': suggestion != normalised,
    }


def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    counter = Counter(tokenize(text))
    return counter.most_common() if limit is None else counter.most_common(max(0, limit))


def lemma_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    counter = Counter(get_lemma(t) for t in tokenize(text))
    return counter.most_common() if limit is None else counter.most_common(max(0, limit))


def word_to_lemma_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for token in tokenize(text):
        mapping.setdefault(token, get_lemma(token))
    return mapping


def filter_stopwords(tokens: Iterable[str], *, stopwords: set[str] | None = None) -> list[str]:
    """Optional stopword filtering; the original token stream is untouched."""
    blocked = STOP_WORDS if stopwords is None else stopwords
    blocked_norm = {normalise_token(w) for w in blocked}
    return [t for t in tokens if normalise_token(t) not in blocked_norm]
