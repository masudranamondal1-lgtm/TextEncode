from modules.bengali_nlp import BengaliAnalyzer, extract_candidates


def test_token_offsets_preserve_original_passage_positions():
    text = "নদীর ধারে ইছামতী বয়ে যায়।"
    tokens = BengaliAnalyzer().process_text(text)
    for token in tokens:
        assert text[token["start"]:token["end"]] == token["surface"]


def test_candidate_has_explanation_and_db_fields():
    passage = {"doc_id": "DOC-001", "passage_id": "DOC-001-P001", "plain_text": "শ্রীমতী কমলা নদীর ধারে থাকেন।"}
    cat_map = {"person": 1, "river or hydrological feature": 2, "other": 12}
    result = extract_candidates([passage], cat_map, [])
    assert result
    candidate = next(x for x in result if x["surface_form"] == "কমলা")
    assert candidate["recognition_method"] == "bengali_rules_v1"
    assert "প্রস্তাবের কারণ" in candidate["contextual_evidence"]
    assert candidate["char_start"] >= 0
    assert passage["plain_text"][candidate["char_start"]:candidate["char_end"]] == candidate["surface_form"]
    assert 0 <= candidate["confidence_score"] <= 1


def test_existing_entities_are_not_suggested_again():
    passage = {"doc_id": "D1", "passage_id": "P1", "plain_text": "ইছামতী নদীর পাশে গ্রাম।"}
    found = extract_candidates([passage], {"river or hydrological feature": 2, "place": 3, "other": 4}, [{"canonical_name": "ইছামতী"}])
    assert all(x["surface_form"] != "ইছামতী" for x in found)


def test_progress_callback_runs_per_passage():
    seen = []
    passages = [{"doc_id": "D", "passage_id": "P1", "plain_text": "নদীর ধারে গ্রাম।"}]
    extract_candidates(passages, {"other": 1}, [], lambda current, total: seen.append((current, total)))
    assert seen == [(1, 1)]


def test_existing_sqlite_style_row_mapping_is_supported():
    class RowLike:
        def __getitem__(self, key):
            return {"canonical_name": "ইছামতী", "alt_names": "ইছামতি; ইছামতী নদী"}[key]
    passage = {"doc_id": "D1", "passage_id": "P1", "plain_text": "ইছামতী নদীর পাশে গ্রাম।"}
    found = extract_candidates([passage], {"other": 4}, [RowLike()])
    assert all(x["surface_form"] != "ইছামতী" for x in found)
