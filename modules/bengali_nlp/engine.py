"""Bengali NLP Engine Orchestrator."""

import re
from datetime import datetime, timezone
from .morphology.exceptions import STOPWORDS, CLASSIFIERS, TITLES, HEAD_NOUNS
from .morphology.verb_analyzer import is_verb
from .morphology.noun_analyzer import strip_case_markers, get_head_noun_category
from .morphology.compound_analyzer import is_valid_compound_modifier

def tokenize(text: str) -> list[dict]:
    return [
        {"surface": m.group(), "start": m.start(), "end": m.end()} 
        for m in re.finditer(r"[\u0980-\u09FF]+", text)
    ]

def _make_cand(p, surface, start, end, cat_id, score, method, evidence):
    return {
        "doc_id": p["doc_id"], "passage_id": p["passage_id"],
        "surface_form": surface.strip(), "char_start": start, "char_end": end,
        "suggested_category_id": cat_id, "confidence_score": score,
        "recognition_method": method, "contextual_evidence": evidence,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }

def extract_candidates(passages: list, cat_map: dict, existing_entities: list, progress_callback=None) -> list[dict]:
    all_candidates = []
    
    known_roots = {}
    for e in existing_entities:
        known_roots[e["canonical_name"].lower()] = e["category_id"]
        # FIXED: sqlite3.Row does not have .get(), access directly
        alt_names = e["alt_names"]
        if alt_names:
            for alt in alt_names.split(","):
                known_roots[alt.strip().lower()] = e["category_id"]

    person_cat_id = cat_map.get("person")
    total = len(passages)
    
    for idx, p in enumerate(passages):
        text = p["plain_text"]
        if not text.strip():
            if progress_callback: progress_callback(idx + 1, total)
            continue
            
        tokens = tokenize(text)
        
        for i, t in enumerate(tokens):
            word = t["surface"]
            
            if word in STOPWORDS or word in CLASSIFIERS or is_verb(word):
                continue
                
            root = strip_case_markers(word)
            
            if root in known_roots:
                all_candidates.append(_make_cand(p, word, t["start"], t["end"], known_roots[root], 0.95, "dictionary", "Matched known entity"))
                continue
                
            if i < len(tokens) - 1:
                next_word = tokens[i+1]["surface"]
                if next_word in TITLES:
                    all_candidates.append(_make_cand(p, word, t["start"], t["end"], person_cat_id, 0.90, "grammar_title", f"Name preceded title '{next_word}'"))
                    continue
                    
            head_noun_cat = get_head_noun_category(root, HEAD_NOUNS)
            if head_noun_cat and i > 0:
                prev_t = tokens[i-1]
                prev_word = prev_t["surface"]
                prev_root = strip_case_markers(prev_word)
                
                if is_valid_compound_modifier(prev_word, prev_root, known_roots, person_cat_id):
                    compound = f"{prev_word} {word}"
                    cat_id = cat_map.get(head_noun_cat) or cat_map.get("other")
                    all_candidates.append(_make_cand(p, compound, prev_t["start"], t["end"], cat_id, 0.85, "grammar_compound", f"Head Noun '{word}' preceded by '{prev_word}'"))
                    continue

        if progress_callback:
            progress_callback(idx + 1, total)
            
    seen = set()
    unique_candidates = []
    for c in all_candidates:
        key = (c["passage_id"], c["char_start"], c["char_end"])
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)
            
    return unique_candidates
