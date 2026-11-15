"""SQLite persistence for TextEncode."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"
SCHEMA_VERSION = 1

class DuplicateDocumentError(Exception):
    def __init__(self, existing_doc_id: str):
        self.existing_doc_id = existing_doc_id
        super().__init__(f"This exact file has already been imported as {existing_doc_id}.")

DEFAULT_CATEGORIES = [
    ("Person", "Individuals, historical figures and literary characters."),
    ("Plant", "Trees, shrubs, crops, flowers and other plant life."),
    ("Animal", "Animals, birds, fish, insects and other fauna."),
    ("Place", "Settlements, regions, buildings and geographical locations."),
    ("River or hydrological feature", "Rivers, tributaries, canals, wetlands and other water bodies."),
    ("Institution", "Formal or informal organisations and institutions."),
    ("Material object", "Physical objects, tools, artefacts and infrastructure."),
    ("Economic activity", "Occupations, production, exchange, trade and livelihood activities."),
    ("Event", "Historical, social, political, ecological or narrative events."),
    ("Cultural practice", "Rituals, customs, traditions and social practices."),
    ("Ecological entity", "Ecosystems, habitats and ecological formations."),
    ("Other", "Entities that do not fit the existing categories."),
]

DEFAULT_RELATIONSHIP_TYPES = [
    ("inhabits", "Source lives in or occupies target.", 1),
    ("depends_on", "Source relies on target for livelihood or survival.", 1),
    ("affects", "Source acts upon or influences target.", 1),
    ("uses", "Source makes practical use of target.", 1),
    ("owns", "Source holds target as property.", 1),
    ("controls", "Source exercises control over target.", 1),
    ("governs", "Source administers or rules target.", 1),
    ("trades_with", "Source exchanges goods or services with target.", 1),
    ("exploits", "Source extracts value from target.", 1),
    ("protects", "Source safeguards target.", 1),
    ("contests", "Source disputes, resists or competes with target.", 1),
    ("remembers", "Source commemorates or recalls target.", 1),
    ("represents", "Source stands for or symbolises target.", 1),
    ("transforms", "Source changes the state or form of target.", 1),
    ("connected_to", "General association; treat as undirected.", 0),
    ("other", "Any other relationship; describe it in the notes.", 1),
]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, original_filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE, language TEXT, author TEXT, publication_info TEXT,
    source_text TEXT NOT NULL, import_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    passage_type TEXT NOT NULL, sequence INTEGER NOT NULL, heading_level INTEGER,
    heading_path TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, plain_text TEXT NOT NULL,
    char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, content_hash TEXT NOT NULL,
    UNIQUE (doc_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_passages_doc ON passages(doc_id);

CREATE TABLE IF NOT EXISTS entity_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, is_default INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, category_id INTEGER NOT NULL REFERENCES entity_categories(category_id),
    alt_names TEXT, transliteration TEXT, description TEXT, notes TEXT,
    doc_id TEXT REFERENCES documents(doc_id) ON DELETE SET NULL, created_at TEXT NOT NULL,
    latitude REAL, longitude REAL, geometry_type TEXT DEFAULT 'Point', location_status TEXT DEFAULT 'Uncertain'
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);

CREATE TABLE IF NOT EXISTS mentions (
    mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
    surface_form TEXT NOT NULL, char_start INTEGER, char_end INTEGER, status TEXT NOT NULL DEFAULT 'verified',
    note TEXT, created_at TEXT NOT NULL, UNIQUE (entity_id, passage_id, char_start, char_end)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);

CREATE TABLE IF NOT EXISTS relationship_types (
    type_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, directed INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, type_id INTEGER NOT NULL REFERENCES relationship_types(type_id),
    description TEXT, evidence_passage_id TEXT REFERENCES passages(passage_id) ON DELETE SET NULL,
    doc_id TEXT REFERENCES documents(doc_id) ON DELETE SET NULL, note TEXT, confidence TEXT, created_at TEXT NOT NULL
);
"""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

@contextmanager
def get_connection(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _seed_defaults(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO entity_categories (name, description, is_default) VALUES (?, ?, 1)", DEFAULT_CATEGORIES)
    conn.executemany("INSERT INTO relationship_types (name, description, directed, is_default) VALUES (?, ?, ?, 1)", DEFAULT_RELATIONSHIP_TYPES)

def init_db(db_path: str | Path | None = None) -> None:
    with get_connection(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(_SCHEMA_SQL)
            _seed_defaults(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        
        # Safe migration for QGIS columns (Stage 6)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(entities)").fetchall()]
        if "latitude" not in cols:
            conn.execute("ALTER TABLE entities ADD COLUMN latitude REAL")
        if "longitude" not in cols:
            conn.execute("ALTER TABLE entities ADD COLUMN longitude REAL")
        if "geometry_type" not in cols:
            conn.execute("ALTER TABLE entities ADD COLUMN geometry_type TEXT DEFAULT 'Point'")
        if "location_status" not in cols:
            conn.execute("ALTER TABLE entities ADD COLUMN location_status TEXT DEFAULT 'Uncertain'")
        
        # FTS5 Search Table
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(
                passage_id UNINDEXED, doc_id UNINDEXED, plain_text, tokenize='unicode61 remove_diacritics 2'
            );
        """)
        fts_count = conn.execute("SELECT COUNT(*) FROM passage_search").fetchone()[0]
        if fts_count == 0:
            rows = conn.execute("SELECT passage_id, doc_id, plain_text FROM passages").fetchall()
            if rows:
                conn.executemany("INSERT INTO passage_search (passage_id, doc_id, plain_text) VALUES (?, ?, ?)", [(r[0], r[1], r[2]) for r in rows])

def _next_sequential_id(conn, table, column, prefix, width) -> str:
    row = conn.execute(f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1", (f"{prefix}-%",)).fetchone()
    number = 1 if row is None else int(row[0].split("-")[1]) + 1
    return f"{prefix}-{number:0{width}d}"

def next_doc_id(conn) -> str: return _next_sequential_id(conn, "documents", "doc_id", "DOC", 3)
def next_entity_id(conn) -> str: return _next_sequential_id(conn, "entities", "entity_id", "ENT", 6)
def next_mention_id(conn) -> str: return _next_sequential_id(conn, "mentions", "mention_id", "MEN", 6)
def next_relationship_id(conn) -> str: return _next_sequential_id(conn, "relationships", "relationship_id", "REL", 6)

def save_document(conn, *, title: str, original_filename: str, source_text: str, passages: list[dict], language: str | None = None, author: str | None = None, publication_info: str | None = None) -> str:
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    existing = conn.execute("SELECT doc_id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
    if existing is not None: raise DuplicateDocumentError(existing["doc_id"])

    doc_id = next_doc_id(conn)
    conn.execute("INSERT INTO documents (doc_id, title, original_filename, file_hash, language, author, publication_info, source_text, import_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (doc_id, title, original_filename, file_hash, language, author, publication_info, source_text, utc_now()))
    rows = []
    search_rows = []
    for sequence, passage in enumerate(passages, start=1):
        passage_id = f"{doc_id}-P{sequence:03d}"
        rows.append((passage_id, doc_id, passage["passage_type"], sequence, passage.get("heading_level"), passage.get("heading_path") or "", passage["text"], passage["plain_text"], passage["char_start"], passage["char_end"], passage["content_hash"]))
        search_rows.append((passage_id, doc_id, passage["plain_text"]))
    conn.executemany("INSERT INTO passages (passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO passage_search (passage_id, doc_id, plain_text) VALUES (?, ?, ?)", search_rows)
    return doc_id

def list_documents(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT doc_id, title, original_filename, file_hash, language, author, publication_info, import_date, (SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) AS passage_count FROM documents d ORDER BY d.doc_id").fetchall()

def get_document(conn, doc_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()

def get_passages(conn, doc_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()

def get_passages_paginated(conn, doc_id: str, limit: int = 25, offset: int = 0) -> list[sqlite3.Row]:
    return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages WHERE doc_id = ? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()

def count_passages(conn, doc_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM passages WHERE doc_id = ?", (doc_id,)).fetchone()[0]

def get_all_passages(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages ORDER BY doc_id, sequence").fetchall()

def search_passages_fts(conn, query: str, doc_id: str | None = None) -> list[sqlite3.Row]:
    if doc_id:
        return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? AND p.doc_id = ? ORDER BY rank", (query, doc_id)).fetchall()
    return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? ORDER BY rank", (query,)).fetchall()

def delete_document(conn, doc_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM passage_search WHERE doc_id = ?", (doc_id,))

def database_stats(conn) -> dict:
    tables = {"documents": "documents", "passages": "passages", "entities": "entities", "mentions": "mentions", "relationships": "relationships", "categories": "entity_categories"}
    return {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in tables.items()}

def get_categories(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT category_id, name, description FROM entity_categories ORDER BY category_id").fetchall()

def save_entity(conn, *, canonical_name: str, category_id: int, alt_names: str | None = None, transliteration: str | None = None, description: str | None = None, notes: str | None = None, doc_id: str | None = None, latitude: float | None = None, longitude: float | None = None, geometry_type: str = 'Point', location_status: str = 'Uncertain') -> str:
    entity_id = next_entity_id(conn)
    conn.execute("INSERT INTO entities (entity_id, canonical_name, category_id, alt_names, transliteration, description, notes, doc_id, created_at, latitude, longitude, geometry_type, location_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (entity_id, canonical_name, category_id, alt_names, transliteration, description, notes, doc_id, utc_now(), latitude, longitude, geometry_type, location_status))
    return entity_id

def get_entities(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT e.entity_id, e.canonical_name, c.name as category, e.alt_names, e.transliteration, e.description, e.notes, e.doc_id, e.created_at, e.latitude, e.longitude, e.geometry_type, e.location_status FROM entities e JOIN entity_categories c ON e.category_id = c.category_id ORDER BY e.entity_id").fetchall()

def update_entity(conn, entity_id: str, *, canonical_name: str, category_id: int, alt_names: str | None, transliteration: str | None, description: str | None, notes: str | None, latitude: float | None, longitude: float | None, geometry_type: str, location_status: str) -> None:
    conn.execute("UPDATE entities SET canonical_name = ?, category_id = ?, alt_names = ?, transliteration = ?, description = ?, notes = ?, latitude = ?, longitude = ?, geometry_type = ?, location_status = ? WHERE entity_id = ?", (canonical_name, category_id, alt_names, transliteration, description, notes, latitude, longitude, geometry_type, location_status, entity_id))

def delete_entity(conn, entity_id: str) -> None:
    conn.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))

def save_mention(conn, *, entity_id: str, doc_id: str, passage_id: str, surface_form: str, char_start: int | None = None, char_end: int | None = None, note: str | None = None, status: str = 'verified') -> str:
    mention_id = next_mention_id(conn)
    conn.execute("INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, status, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, status, note, utc_now()))
    return mention_id

def get_mentions(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT m.mention_id, m.surface_form, m.status, m.note, m.created_at, m.char_start, m.char_end, e.entity_id, e.canonical_name, c.name as category, p.passage_id, p.plain_text, p.doc_id FROM mentions m JOIN entities e ON m.entity_id = e.entity_id JOIN entity_categories c ON e.category_id = c.category_id JOIN passages p ON m.passage_id = p.passage_id ORDER BY m.mention_id DESC").fetchall()

def get_mentions_for_document(conn, doc_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT passage_id, entity_id, surface_form, char_start, char_end FROM mentions WHERE doc_id = ? AND char_start IS NOT NULL AND char_end IS NOT NULL", (doc_id,)).fetchall()

def delete_mention(conn, mention_id: str) -> None:
    conn.execute("DELETE FROM mentions WHERE mention_id = ?", (mention_id,))

def get_relationship_types(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT type_id, name, description, directed FROM relationship_types ORDER BY type_id").fetchall()

def save_relationship(conn, *, source_entity_id: str, target_entity_id: str, type_id: int, description: str | None = None, evidence_passage_id: str | None = None, doc_id: str | None = None, note: str | None = None, confidence: str | None = None) -> str:
    relationship_id = next_relationship_id(conn)
    conn.execute("INSERT INTO relationships (relationship_id, source_entity_id, target_entity_id, type_id, description, evidence_passage_id, doc_id, note, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (relationship_id, source_entity_id, target_entity_id, type_id, description, evidence_passage_id, doc_id, note, confidence, utc_now()))
    return relationship_id

def get_relationships(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT r.relationship_id, r.source_entity_id, s.canonical_name as source_name, r.target_entity_id, t.canonical_name as target_name, rt.name as relationship_type, r.description, r.confidence, r.evidence_passage_id, p.plain_text as evidence_text FROM relationships r JOIN entities s ON r.source_entity_id = s.entity_id JOIN entities t ON r.target_entity_id = t.entity_id JOIN relationship_types rt ON r.type_id = rt.type_id LEFT JOIN passages p ON r.evidence_passage_id = p.passage_id ORDER BY r.relationship_id DESC").fetchall()

def delete_relationship(conn, relationship_id: str) -> None:
    conn.execute("DELETE FROM relationships WHERE relationship_id = ?", (relationship_id,))