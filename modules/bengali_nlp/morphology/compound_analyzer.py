"""Bengali Compound Analyzer."""

from .exceptions import STOPWORDS, CLASSIFIERS
from .verb_analyzer import is_verb

def is_valid_compound_modifier(prev_word: str, prev_root: str, known_entities: dict, person_cat_id: int) -> bool:
    if prev_word in STOPWORDS or prev_word in CLASSIFIERS or is_verb(prev_word):
        return False
    is_prev_person = prev_root in known_entities and known_entities[prev_root] == person_cat_id
    if is_prev_person:
        return False
    return True
