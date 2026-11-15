"""Lightweight linguistic analysis for TextEncode.

This module provides a rule-based morphological stemmer (lemmatizer) for Bengali.
It strips common case markers and plural suffixes (e.g., নদী, নদীর, নদীতে -> নদী).

IMPORTANT: This is a *lightweight rule-based* approach, not a full NLP model.
It may occasionally over-strip, but it preserves the original text and is 
extremely fast for 100,000-word documents.
"""

from __future__ import annotations
from collections import Counter
import re

#: Common Bengali suffixes (case markers, plurals, classifiers).
#: Ordered from longest to shortest so we match the most specific suffix first.
BENGALI_SUFFIXES = [
    "গুলির", "গুলোতে", "গুলিতে", "গুলোকে", "গুলোর", 
    "গুলি", "গুলো", "দের", "কে", "তে", "রে", "ের", "টি", "টা", "রা", "র"
]

_EDGE_PUNCTUATION = "।॥.,;:!?\"'“”‘’«»()[]{}<>—–-…*_`~|/\\+=#"

def normalise_token(token: str) -> str:
    """Trim edge punctuation from a whitespace token and case-fold it."""
    return token.strip(_EDGE_PUNCTUATION).casefold()

def tokenize(text: str) -> list[str]:
    """Return normalised word tokens."""
    tokens = []
    for raw in text.split():
        token = normalise_token(raw)
        if token:
            tokens.append(token)
    return tokens

def get_lemma(token: str) -> str:
    """Return the approximate base form (lemma) of a Bengali token.
    
    Example: নদীর -> নদী, নদীতে -> নদী, নদীগুলি -> নদী
    """
    if not token:
        return token
        
    for suffix in BENGALI_SUFFIXES:
        # Only strip if the resulting word is at least 2 characters long
        # and the token actually ends with the suffix.
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[:-len(suffix)]
            
    return token

def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    """Return surface-form frequencies."""
    counter = Counter(tokenize(text))
    return counter.most_common() if limit is None else counter.most_common(limit)

def lemma_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    """Return grouped lemma frequencies."""
    tokens = tokenize(text)
    lemmas = [get_lemma(t) for t in tokens]
    counter = Counter(lemmas)
    return counter.most_common() if limit is None else counter.most_common(limit)

def word_to_lemma_map(text: str) -> dict[str, str]:
    """Return a mapping of surface forms to their lemmas for display."""
    tokens = tokenize(text)
    mapping = {}
    for t in tokens:
        if t not in mapping:
            mapping[t] = get_lemma(t)
    return mapping