"""Bengali Noun Analyzer."""

CASE_MARKERS = ["গুলোতে", "গুলিতে", "গুলোকে", "গুলোর", "টিতে", "টাতে", "গুলো", "গুলি", "দের", "টির", "টার", "ের", "র", "কে", "তে", "য়ে", "য়", "রা"]

def strip_case_markers(word: str) -> str:
    for m in CASE_MARKERS:
        if word.endswith(m) and len(word) > len(m) + 1:
            return word[:-len(m)]
    return word

def get_head_noun_category(root: str, head_nouns: dict) -> str | None:
    for cat, nouns in head_nouns.items():
        if root in nouns:
            return cat
    return None
