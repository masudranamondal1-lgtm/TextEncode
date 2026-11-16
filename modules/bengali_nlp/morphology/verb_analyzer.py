"""Bengali Verb Analyzer."""

VERB_ENDINGS = {"চ্ছে", "য়েছে", "তেছে", "লাম", "লেন", "বেন", "তাম", "তেন", "ছে", "লো", "বে", "ল", "ত", "ব", "রা"}

def is_verb(word: str) -> bool:
    return any(word.endswith(v) for v in VERB_ENDINGS) and len(word) > 2
