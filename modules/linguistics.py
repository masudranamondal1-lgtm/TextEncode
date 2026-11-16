"""Linguistic analysis for TextEncode."""

from __future__ import annotations
from collections import Counter
import re

# Regex adapted from the user's page.html for precise Bengali/English tokenization
TOKEN_RE = re.compile(r'[\u0980-\u09FF]+|[A-Za-z]+|\d+|[^\s\u0980-\u09FFA-Za-z\d]+')

# Stopwords adapted from page.html
STOP_WORDS = set(['আর', 'কি', 'কে', 'যে', 'যা', 'এই', 'সেই', 'এ', 'ও', 'না', 'হয়', 'থাক', 'তবু', 'তার', 'করে', 'করা', 'হলো', 'হল', 'নেই', 'আরও', 'কিন্তু', 'এখন', 'এক', 'একটি', 'সব', 'মনে', 'মতো', 'হয়ে', 'যায়', 'গেছে', 'ছিল', 'আমি', 'তুমি', 'এবং', 'তাই', 'তবে', 'সে', 'ওই', 'হয়েছে', 'হবে', 'হয়েই', 'হচ্ছে', 'তোমার', 'আমার', 'তার', 'যেন', 'কেন', 'কারণ', 'কোনও', 'একা', 'আবার', 'অনেক', 'সেখানে', 'এখানে', 'সেই', 'এই'])

BENGALI_SUFFIXES = [
    "গুলির", "গুলোতে", "গুলিতে", "গুলোকে", "গুলোর", 
    "গুলি", "গুলো", "দের", "কে", "তে", "রে", "ের", "টি", "টা", "রা", "র"
]

def tokenize(text: str) -> list[str]:
    """Return normalised word tokens using the HTML app's regex logic."""
    raw_tokens = TOKEN_RE.findall(text)
    tokens = []
    for raw in raw_tokens:
        # Clean edge punctuation for Bengali/English words
        token = raw.strip("।॥.,;:!?\"'“”‘’«»()[]{}<>—–-…*_`~|/\\+=#").casefold()
        if token and not token.isspace():
            tokens.append(token)
    return tokens

def get_lemma(token: str) -> str:
    """Return the approximate base form (lemma) of a Bengali token."""
    if not token:
        return token
    for suffix in BENGALI_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[:-len(suffix)]
    return token

def word_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    tokens = tokenize(text)
    counter = Counter(tokens)
    return counter.most_common() if limit is None else counter.most_common(limit)

def lemma_frequencies(text: str, limit: int | None = 50) -> list[tuple[str, int]]:
    tokens = tokenize(text)
    lemmas = [get_lemma(t) for t in tokens]
    counter = Counter(lemmas)
    return counter.most_common() if limit is None else counter.most_common(limit)

def word_to_lemma_map(text: str) -> dict[str, str]:
    tokens = tokenize(text)
    mapping = {}
    for t in tokens:
        if t not in mapping:
            mapping[t] = get_lemma(t)
    return mapping