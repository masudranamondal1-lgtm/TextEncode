"""Text Analysis Engine (Statistics, N-grams, KWIC)."""

from collections import Counter
import re
from modules.linguistics import tokenize

def get_basic_stats(text: str) -> dict:
    """Calculates fundamental statistics for a text."""
    tokens = tokenize(text)
    sentences = [s.strip() for s in re.split(r'[।.!?]+', text) if s.strip()]
    
    word_count = len(tokens)
    sentence_count = len(sentences)
    
    return {
        "word_count": word_count,
        "unique_words": len(set(tokens)),
        "char_count": len(text),
        "char_count_no_whitespace": sum(1 for c in text if not c.isspace()),
        "sentence_count": sentence_count,
        "avg_sentence_length": round(word_count / sentence_count, 2) if sentence_count > 0 else 0,
    }

def get_word_frequency(text: str, limit: int = 50, min_length: int = 1) -> list[tuple[str, int]]:
    """Returns the most common words."""
    tokens = [t for t in tokenize(text) if len(t) >= min_length]
    return Counter(tokens).most_common(limit)

def get_ngrams(text: str, n: int = 2, limit: int = 50) -> list[tuple[str, int]]:
    """Returns the most common n-grams (bigrams, trigrams, etc.)."""
    tokens = tokenize(text)
    if len(tokens) < n:
        return []
    
    ngrams = zip(*[tokens[i:] for i in range(n)])
    # Join with space for display
    ngram_strings = [" ".join(gram) for gram in ngrams]
    return Counter(ngram_strings).most_common(limit)

def get_kwic(text: str, query: str, window: int = 40, limit: int = 100) -> list[dict]:
    """Keyword in Context (Concordance)."""
    results = []
    # Use regex to find exact matches, case-insensitive
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    
    for match in pattern.finditer(text):
        start, end = match.span()
        left = text[max(0, start - window):start].replace("\n", " ")
        right = text[end:end + window].replace("\n", " ")
        
        results.append({
            "match": text[start:end],
            "left": f"...{left}",
            "right": f"{right}...",
            "start": start,
            "end": end
        })
        
        if len(results) >= limit:
            break
            
    return results
