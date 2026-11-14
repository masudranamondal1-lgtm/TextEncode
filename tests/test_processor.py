"""Tests for modules.processor."""

from modules import processor


def test_tokenize_keeps_bengali_combining_marks():
    # Regression test: r"\w+" would split these words at া / ী.
    tokens = processor.tokenize("ইছামতী নদী শান্ত ছিল।")
    assert tokens == ["ইছামতী", "নদী", "শান্ত", "ছিল"]


def test_tokenize_strips_edge_punctuation_and_casefolds():
    assert processor.tokenize("Hello, (World)!") == ["hello", "world"]


def test_word_count_ignores_punctuation_only_tokens():
    assert processor.count_words("Hello, world! — ok") == 3


def test_sentence_count_bengali():
    text = "প্রথম বাক্য। দ্বিতীয় বাক্য। তৃতীয় বাক্য"
    assert processor.count_sentences(text) == 3


def test_sentence_count_english():
    assert processor.count_sentences("One. Two! Three?") == 3


def test_document_statistics_counts_types():
    passages = [
        {"passage_type": "heading", "plain_text": "Title"},
        {"passage_type": "paragraph", "plain_text": "ইছামতী নদী শান্ত ছিল।"},
        {"passage_type": "list_item", "plain_text": "item"},
        {"passage_type": "code_block", "plain_text": "x = 1"},
    ]
    stats = processor.document_statistics("# Title\n\nইছামতী নদী শান্ত ছিল।\n",
                                          passages)
    assert stats["passage_count"] == 4
    assert stats["heading_count"] == 1
    assert stats["paragraph_count"] == 1
    assert stats["list_item_count"] == 1
    assert stats["word_count"] == 5  # "title ichhamati nodi shanto chilo" equivalents


def test_search_is_case_insensitive_by_default():
    passages = [{
        "doc_id": "DOC-001", "passage_id": "DOC-001-P001", "sequence": 1,
        "passage_type": "paragraph", "heading_path": "",
        "plain_text": "The Ichhamati river flows on.",
    }]
    results = processor.search_passages(passages, "ichhamati")
    assert len(results) == 1
    assert results[0]["match_count"] == 1


def test_search_respects_case_sensitivity():
    passages = [{
        "doc_id": "DOC-001", "passage_id": "DOC-001-P001", "sequence": 1,
        "passage_type": "paragraph", "heading_path": "",
        "plain_text": "The Ichhamati river flows on.",
    }]
    assert processor.search_passages(passages, "ichhamati", case_sensitive=True) == []


def test_search_returns_empty_for_blank_query():
    assert processor.search_passages([], "   ") == []
