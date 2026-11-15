"""SQLite persistence for TextEncode v0.3."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"
SCHEMA_VERSION = 2

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

def init_db(db_path: str | Path | None = None) -> None:
    """Self-healing schema initialization and migration."""
    with get_connection(db_path) as conn:
        # 1. Ensure core tables exist
        conn.executescript("""
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
            CREATE TABLE IF NOT EXISTS mentions (
                mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, 
                passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
                surface_form TEXT NOT NULL, char_start INTEGER, char_end INTEGER, status TEXT NOT NULL DEFAULT 'verified',
                note TEXT, created_at TEXT NOT NULL, UNIQUE (entity_id, passage_id, char_start, char_end)
            );
        """)
        
        # 2. Ensure v0.3 tables exist
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS taxonomy_profiles (
                profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE, description TEXT, is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attribute_definitions (
                attribute_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
                target_table TEXT NOT NULL, category_id INTEGER, name TEXT NOT NULL, data_type TEXT NOT NULL, description TEXT
            );
            CREATE TABLE IF NOT EXISTS attribute_values (
                value_id INTEGER PRIMARY KEY AUTOINCREMENT, attribute_id INTEGER NOT NULL,
                entity_id TEXT, relationship_id TEXT, value_text TEXT
            );
                        CREATE TABLE IF NOT EXISTS entity_candidates (
                candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
                surface_form TEXT NOT NULL,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                suggested_category_id INTEGER REFERENCES entity_categories(category_id),
                confidence_score REAL DEFAULT 0.0,
                recognition_method TEXT,
                contextual_evidence TEXT,
                review_status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
        """)
        
        # 3. Ensure all columns exist using helper function
        def add_col(table, col, definition):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

        # entity_categories
        conn.execute("CREATE TABLE IF NOT EXISTS entity_categories (category_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        add_col("entity_categories", "profile_id", "INTEGER DEFAULT 1")
        add_col("entity_categories", "parent_id", "INTEGER")
        add_col("entity_categories", "description", "TEXT")
        add_col("entity_categories", "color", "TEXT DEFAULT '#808080'")
        add_col("entity_categories", "icon", "TEXT DEFAULT '📦'")
        add_col("entity_categories", "inclusion_rules", "TEXT")
        add_col("entity_categories", "exclusion_rules", "TEXT")
        add_col("entity_categories", "is_default", "INTEGER NOT NULL DEFAULT 0")

        # relationship_types
        conn.execute("CREATE TABLE IF NOT EXISTS relationship_types (type_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        add_col("relationship_types", "profile_id", "INTEGER DEFAULT 1")
        add_col("relationship_types", "group_name", "TEXT DEFAULT 'General'")
        add_col("relationship_types", "description", "TEXT")
        add_col("relationship_types", "directed", "INTEGER NOT NULL DEFAULT 1")
        add_col("relationship_types", "inverse_type_id", "INTEGER")
        add_col("relationship_types", "source_category_id", "INTEGER")
        add_col("relationship_types", "target_category_id", "INTEGER")
        add_col("relationship_types", "is_default", "INTEGER NOT NULL DEFAULT 0")

        # entities
        conn.execute("CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, category_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        add_col("entities", "profile_id", "INTEGER DEFAULT 1")
        add_col("entities", "alt_names", "TEXT")
        add_col("entities", "transliteration", "TEXT")
        add_col("entities", "description", "TEXT")
        add_col("entities", "notes", "TEXT")
        add_col("entities", "doc_id", "TEXT")
        add_col("entities", "latitude", "REAL")
        add_col("entities", "longitude", "REAL")
        add_col("entities", "geometry_type", "TEXT DEFAULT 'Point'")
        add_col("entities", "location_status", "TEXT DEFAULT 'Uncertain'")

        # relationships
        conn.execute("CREATE TABLE IF NOT EXISTS relationships (relationship_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL, type_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        add_col("relationships", "description", "TEXT")
        add_col("relationships", "evidence_passage_id", "TEXT")
        add_col("relationships", "doc_id", "TEXT")
        add_col("relationships", "note", "TEXT")
        add_col("relationships", "confidence", "TEXT")

        # 4. Seed default taxonomy if empty
        count = conn.execute("SELECT COUNT(*) FROM taxonomy_profiles").fetchone()[0]
        if count == 0:
            conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)", ("General DH Profile", "Default categories", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            cat_count = conn.execute("SELECT COUNT(*) FROM entity_categories").fetchone()[0]
            if cat_count == 0:
                for name, desc in DEFAULT_CATEGORIES:
                    conn.execute("INSERT INTO entity_categories (profile_id, name, description, is_default) VALUES (?, ?, ?, 1)", (pid, name, desc))
            else:
                conn.execute("UPDATE entity_categories SET profile_id = ?", (pid,))
                
            rel_count = conn.execute("SELECT COUNT(*) FROM relationship_types").fetchone()[0]
            if rel_count == 0:
                for name, desc, directed in DEFAULT_RELATIONSHIP_TYPES:
                    conn.execute("INSERT INTO relationship_types (profile_id, name, description, directed, is_default) VALUES (?, ?, ?, ?, 1)", (pid, name, desc, directed))
            else:
                conn.execute("UPDATE relationship_types SET profile_id = ?", (pid,))

        # Ensure entities have profile_id
        conn.execute("UPDATE entities SET profile_id = 1 WHERE profile_id IS NULL")

        # 5. Setup FTS5 Search
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

        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
    rows, search_rows = [], []
    for sequence, passage in enumerate(passages, start=1):
        pid = f"{doc_id}-P{sequence:03d}"
        rows.append((pid, doc_id, passage["passage_type"], sequence, passage.get("heading_level"), passage.get("heading_path") or "", passage["text"], passage["plain_text"], passage["char_start"], passage["char_end"], passage["content_hash"]))
        search_rows.append((pid, doc_id, passage["plain_text"]))
    conn.executemany("INSERT INTO passages (passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO passage_search (passage_id, doc_id, plain_text) VALUES (?, ?, ?)", search_rows)
    return doc_id

def list_documents(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT doc_id, title, original_filename, file_hash, language, author, publication_info, import_date, (SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) AS passage_count FROM documents d ORDER BY d.doc_id").fetchall()

def get_document(conn, doc_id: str) -> sqlite3.Row | None: return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
def get_passages(conn, doc_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
def get_passages_paginated(conn, doc_id: str, limit: int = 25, offset: int = 0) -> list[sqlite3.Row]: return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages WHERE doc_id = ? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
def count_passages(conn, doc_id: str) -> int: return conn.execute("SELECT COUNT(*) FROM passages WHERE doc_id = ?", (doc_id,)).fetchone()[0]
def get_all_passages(conn) -> list[sqlite3.Row]: return conn.execute("SELECT passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash FROM passages ORDER BY doc_id, sequence").fetchall()

def search_passages_fts(conn, query: str, doc_id: str | None = None) -> list[sqlite3.Row]:
    if doc_id: return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? AND p.doc_id = ? ORDER BY rank", (query, doc_id)).fetchall()
    return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? ORDER BY rank", (query,)).fetchall()

def delete_document(conn, doc_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM passage_search WHERE doc_id = ?", (doc_id,))

def database_stats(conn) -> dict:
    tables = {"documents": "documents", "passages": "passages", "entities": "entities", "mentions": "mentions", "relationships": "relationships", "categories": "entity_categories"}
    return {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in tables.items()}

# --- TAXONOMY ---
def get_profiles(conn) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM taxonomy_profiles ORDER BY profile_id").fetchall()
def get_categories(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM entity_categories WHERE profile_id = ? ORDER BY name", (profile_id,)).fetchall()
def save_category(conn, *, profile_id: int, name: str, description: str, parent_id: int | None = None) -> int:
    conn.execute("INSERT INTO entity_categories (profile_id, parent_id, name, description) VALUES (?, ?, ?, ?)", (profile_id, parent_id, name, description))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def get_relationship_types(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM relationship_types WHERE profile_id = ? ORDER BY group_name, name", (profile_id,)).fetchall()
def save_relationship_type(conn, *, profile_id: int, group_name: str, name: str, description: str, directed: int) -> int:
    conn.execute("INSERT INTO relationship_types (profile_id, group_name, name, description, directed) VALUES (?, ?, ?, ?, ?)", (profile_id, group_name, name, description, directed))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def get_attribute_definitions(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()
def save_attribute_definition(conn, *, profile_id: int, target_table: str, category_id: int | None, name: str, data_type: str, description: str) -> int:
    conn.execute("INSERT INTO attribute_definitions (profile_id, target_table, category_id, name, data_type, description) VALUES (?, ?, ?, ?, ?, ?)", (profile_id, target_table, category_id, name, data_type, description))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

# --- DATA ---
def save_entity(conn, *, profile_id: int, canonical_name: str, category_id: int, alt_names: str | None = None, transliteration: str | None = None, description: str | None = None, notes: str | None = None, doc_id: str | None = None, latitude: float | None = None, longitude: float | None = None, geometry_type: str = 'Point', location_status: str = 'Uncertain') -> str:
    entity_id = next_entity_id(conn)
    conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, alt_names, transliteration, description, notes, doc_id, created_at, latitude, longitude, geometry_type, location_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (entity_id, profile_id, canonical_name, category_id, alt_names, transliteration, description, notes, doc_id, utc_now(), latitude, longitude, geometry_type, location_status))
    return entity_id
def get_entities(conn, profile_id: int = 1) -> list[sqlite3.Row]: return conn.execute("SELECT e.*, c.name as category_name FROM entities e JOIN entity_categories c ON e.category_id = c.category_id WHERE e.profile_id = ? ORDER BY e.entity_id", (profile_id,)).fetchall()
def save_mention(conn, *, entity_id: str, doc_id: str, passage_id: str, surface_form: str, char_start: int | None = None, char_end: int | None = None, note: str | None = None, status: str = 'verified') -> str:
    mention_id = next_mention_id(conn)
    conn.execute("INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, status, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, status, note, utc_now()))
    return mention_id
def save_relationship(conn, *, source_entity_id: str, target_entity_id: str, type_id: int, description: str | None = None, evidence_passage_id: str | None = None, doc_id: str | None = None, note: str | None = None, confidence: str | None = None) -> str:
    relationship_id = next_relationship_id(conn)
    conn.execute("INSERT INTO relationships (relationship_id, source_entity_id, target_entity_id, type_id, description, evidence_passage_id, doc_id, note, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (relationship_id, source_entity_id, target_entity_id, type_id, description, evidence_passage_id, doc_id, note, confidence, utc_now()))
    return relationship_id
# --- AI CANDIDATES ---
def save_candidate(conn, *, doc_id: str, passage_id: str, surface_form: str, char_start: int, char_end: int, suggested_category_id: int | None = None, confidence_score: float = 0.0, recognition_method: str = "heuristic", contextual_evidence: str = "") -> int:
    conn.execute(
        "INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, utc_now())
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_candidates(conn, doc_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT c.*, p.plain_text as passage_text, cat.name as suggested_category_name "
        "FROM entity_candidates c "
        "JOIN passages p ON c.passage_id = p.passage_id "
        "LEFT JOIN entity_categories cat ON c.suggested_category_id = cat.category_id "
        "WHERE c.doc_id = ? AND c.review_status = 'pending' "
        "ORDER BY c.char_start", (doc_id,)
    ).fetchall()

def update_candidate_status(conn, candidate_id: int, status: str) -> None:
    conn.execute("UPDATE entity_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))
    # --- CUSTOM METADATA VALUES ---
def save_attribute_value(conn, *, attribute_id: int, entity_id: str | None = None, relationship_id: str | None = None, value_text: str) -> None:
    conn.execute(
        "INSERT INTO attribute_values (attribute_id, entity_id, relationship_id, value_text) VALUES (?, ?, ?, ?)",
        (attribute_id, entity_id, relationship_id, value_text)
    )

def get_attribute_values(conn, *, entity_id: str | None = None, relationship_id: str | None = None) -> list[sqlite3.Row]:
    if entity_id:
        return conn.execute(
            "SELECT av.*, ad.name, ad.data_type FROM attribute_values av "
            "JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id "
            "WHERE av.entity_id = ?", (entity_id,)
        ).fetchall()
    if relationship_id:
        return conn.execute(
            "SELECT av.*, ad.name, ad.data_type FROM attribute_values av "
            "JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id "
            "WHERE av.relationship_id = ?", (relationship_id,)
        ).fetchall()
    return []