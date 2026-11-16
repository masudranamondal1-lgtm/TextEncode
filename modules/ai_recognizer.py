"""Bridge between TextEncode app and Bengali NLP Engine."""

from modules.bengali_nlp import extract_candidates

def recognize_candidates(passages: list, cat_map: dict, existing_entities: list, progress_callback=None) -> list[dict]:
    return extract_candidates(passages, cat_map, existing_entities, progress_callback)
