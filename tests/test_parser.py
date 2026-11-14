"""Tests for modules.parser.

The central invariant: source[char_start:char_end] == passage["text"].
"""

import pytest

from modules import parser

SOURCE = """# Chapter One

The river was quiet.

- First item
- Second item

> A quoted line.
"""


def test_offsets_match_source_exactly():
    passages = parser.parse_markdown(SOURCE)
    assert passages
    for passage in passages:
        assert SOURCE[passage["char_start"]:passage["char_end"]] == passage["text"]


def test_passage_types_and_order():
    passages = parser.parse_markdown(SOURCE)
    assert [p["passage_type"] for p in passages] == [
        "heading", "paragraph", "list_item", "list_item", "blockquote",
    ]


def test_sequences_are_contiguous():
    passages = parser.parse_markdown(SOURCE)
    assert [p["sequence"] for p in passages] == [1, 2, 3, 4, 5]


def test_heading_path_is_recorded():
    passages = parser.parse_markdown(SOURCE)
    assert passages[0]["heading_path"] == "Chapter One"
    assert passages[1]["heading_path"] == "Chapter One"


def test_headings_carry_level_and_clean_text():
    passages = parser.parse_markdown(SOURCE)
    assert passages[0]["heading_level"] == 1
    assert passages[0]["plain_text"] == "Chapter One"
    assert passages[0]["text"] == "# Chapter One"


def test_bengali_document():
    source = "# অধ্যায় এক\n\nইছামতী নদী শান্ত ছিল।\n"
    passages = parser.parse_markdown(source)
    assert len(passages) == 2
    assert passages[0]["plain_text"] == "অধ্যায় এক"
    assert passages[1]["text"] == "ইছামতী নদী শান্ত ছিল।"
    assert source[passages[1]["char_start"]:passages[1]["char_end"]] == \
        passages[1]["text"]


def test_empty_document_returns_empty_list():
    assert parser.parse_markdown("") == []


def test_crlf_line_endings_are_stripped_from_passages():
    source = "# Title\r\n\r\nBody text.\r\n"
    passages = parser.parse_markdown(source)
    assert passages[0]["text"] == "# Title"
    assert passages[1]["text"] == "Body text."


def test_bare_carriage_return_is_rejected():
    with pytest.raises(ValueError):
        parser.parse_markdown("line one\rline two")


def test_content_hash_is_stable():
    first = parser.parse_markdown(SOURCE)
    second = parser.parse_markdown(SOURCE)
    assert [p["content_hash"] for p in first] == [p["content_hash"] for p in second]


def test_guess_title_prefers_level_one_heading():
    passages = parser.parse_markdown("## Sub\n\ntext\n")
    assert parser.guess_title(passages) == "Sub"
    passages = parser.parse_markdown("text only\n")
    assert parser.guess_title(passages) is None
