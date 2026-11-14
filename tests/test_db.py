"""Tests for database.db (documents and passages)."""

import pytest

from database import db
from modules import parser

DOC = "# Title\n\nBody text.\n"


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def _import(db_path, text=DOC, filename="a.md", title="T"):
    passages = parser.parse_markdown(text)
    with db.get_connection(db_path) as conn:
        return db.save_document(
            conn, title=title, original_filename=filename,
            source_text=text, passages=passages,
        )


def test_import_creates_document_and_passages(db_path):
    doc_id = _import(db_path)
    assert doc_id == "DOC-001"
    with db.get_connection(db_path) as conn:
        document = db.get_document(conn, doc_id)
        assert document["source_text"] == DOC
        passages = db.get_passages(conn, doc_id)
    assert [p["passage_id"] for p in passages] == [
        "DOC-001-P001", "DOC-001-P002",
    ]


def test_duplicate_file_is_refused(db_path):
    _import(db_path)
    with pytest.raises(db.DuplicateDocumentError):
        _import(db_path, filename="b.md")


def test_changed_file_becomes_new_document(db_path):
    assert _import(db_path) == "DOC-001"
    assert _import(db_path, text="# Two\n\nOther.\n", filename="b.md") == "DOC-002"


def test_data_survives_reconnection(db_path):
    doc_id = _import(db_path)
    # A completely new connection to the same file:
    with db.get_connection(db_path) as conn:
        assert db.get_document(conn, doc_id)["title"] == "T"
        assert len(db.get_passages(conn, doc_id)) == 2


def test_delete_cascades_to_passages(db_path):
    doc_id = _import(db_path)
    with db.get_connection(db_path) as conn:
        db.delete_document(conn, doc_id)
        assert db.get_document(conn, doc_id) is None
        assert db.get_passages(conn, doc_id) == []


def test_twelve_default_categories_are_seeded(db_path):
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM entity_categories ORDER BY category_id"
        ).fetchall()
    assert len(rows) == 12
    assert rows[0]["name"] == "Person"
    assert rows[4]["name"] == "River or hydrological feature"


def test_relationship_types_are_seeded(db_path):
    with db.get_connection(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM relationship_types"
        ).fetchone()[0]
    assert count == 16


def test_database_stats(db_path):
    _import(db_path)
    with db.get_connection(db_path) as conn:
        stats = db.database_stats(conn)
    assert stats["documents"] == 1
    assert stats["passages"] == 2
    assert stats["entities"] == 0


def test_mention_id_generation_does_not_collide(db_path):
    with db.get_connection(db_path) as conn:
        assert db.next_entity_id(conn) == "ENT-000001"
