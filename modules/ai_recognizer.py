"""Local heuristic entity recognition for TextEncode."""

import re
from database import db

def _add_candidate_if_new(conn, doc_id, passage_id, surface, start, end, cat_id, conf, method, evidence) -> int:
    if len(surface.strip()) < 2:
        return 0
    existing = conn.execute(
        "SELECT 1 FROM entity_candidates WHERE passage_id = ? AND char_start = ? AND char_end = ? AND review_status = 'pending'",
        (passage_id, start, end)
    ).fetchone()
    if not existing:
        db.save_candidate(
            conn, doc_id=doc_id, passage_id=passage_id, surface_form=surface.strip(), 
            char_start=start, char_end=end, suggested_category_id=cat_id, 
            confidence_score=conf, recognition_method=method, contextual_evidence=evidence
        )
        return 1
    return 0

def recognize_candidates(conn, doc_id: str, profile_id: int) -> int:
    """Scans a document and generates candidate records using Bengali/English heuristics."""
    
    # 1. Fetch existing entities for dictionary matching
    existing_entities = db.get_entities(conn, profile_id)
    entity_dict = {e["canonical_name"].lower(): e["category_id"] for e in existing_entities}

    # 2. Fetch passages
    passages = db.get_passages(conn, doc_id)
    candidates_found = 0

    # Bengali heuristic suffixes (places, people, titles)
    bn_suffix_re = re.compile(r'\b([A-Za-z\u0980-\u09FF]{3,})(বাবু|মশাই|দেবী|নদী|গ্রাম|পুর|খাল|বিল|পুকুর|মাঠ|সাহেব|খাঁ|শেখ|মন্ডল)\b')

    for p in passages:
        text = p["plain_text"]
        
        # Rule 1: Exact match of existing entities (case-insensitive)
        for ent_name, cat_id in entity_dict.items():
            if len(ent_name) < 2: continue
            for match in re.finditer(re.escape(ent_name), text, re.IGNORECASE):
                start, end = match.span()
                candidates_found += _add_candidate_if_new(
                    conn, doc_id, p["passage_id"], text[start:end], start, end, 
                    cat_id, 0.9, "dictionary", f"Matched known entity: {ent_name}"
                )

        # Rule 2: Bengali entity suffixes
        for match in bn_suffix_re.finditer(text):
            start, end = match.span()
            root_word = match.group(1)
            # We suggest the root word (e.g., 'রাম' from 'রামবাবু') or the full word based on preference
            candidates_found += _add_candidate_if_new(
                conn, doc_id, p["passage_id"], match.group(), start, end, 
                None, 0.7, "suffix_heuristic", f"Suffix: -{match.group(2)}"
            )

        # Rule 3: English Proper Nouns
        for match in re.finditer(r'\b[A-Z][a-z]+\b', text):
            start, end = match.span()
            if start == 0 or text[max(0, start-2):start] in (". ", "! ", "? "):
                continue
            candidates_found += _add_candidate_if_new(
                conn, doc_id, p["passage_id"], match.group(), start, end, 
                None, 0.5, "capitalization", "English proper noun"
            )
                
    return candidates_found