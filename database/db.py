"""SQLite persistence for TextEncode v0.4."""

from __future__ import annotations
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"
SCHEMA_VERSION = 3

class DuplicateDocumentError(Exception):
    def __init__(self, existing_doc_id: str):
        self.existing_doc_id = existing_doc_id
        super().__init__(f"This exact file has already been imported as {existing_doc_id}.")

class OffsetValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)

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
    with get_connection(db_path) as conn:
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
            CREATE TABLE IF NOT EXISTS taxonomy_profiles (
                profile_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL
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
                candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
                surface_form TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
                suggested_category_id INTEGER REFERENCES entity_categories(category_id),
                confidence_score REAL DEFAULT 0.0, recognition_method TEXT, contextual_evidence TEXT,
                review_status TEXT DEFAULT 'pending', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL, record_id TEXT NOT NULL, operation TEXT NOT NULL,
                old_value TEXT, new_value TEXT, timestamp TEXT NOT NULL, origin TEXT NOT NULL
            );
        """)
        
        def add_col(table, col, definition):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

        conn.execute("CREATE TABLE IF NOT EXISTS entity_categories (category_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("parent_id", "INTEGER"), ("description", "TEXT"), ("color", "TEXT DEFAULT '#808080'"), ("icon", "TEXT DEFAULT '📦'"), ("is_default", "INTEGER NOT NULL DEFAULT 0")]:
            add_col("entity_categories", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS relationship_types (type_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("group_name", "TEXT DEFAULT 'General'"), ("description", "TEXT"), ("directed", "INTEGER NOT NULL DEFAULT 1"), ("is_default", "INTEGER NOT NULL DEFAULT 0")]:
            add_col("relationship_types", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, category_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("alt_names", "TEXT"), ("transliteration", "TEXT"), ("description", "TEXT"), ("notes", "TEXT"), ("doc_id", "TEXT"), ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_type", "TEXT DEFAULT 'Point'"), ("location_status", "TEXT DEFAULT 'Uncertain'")]:
            add_col("entities", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS relationships (relationship_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL, type_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        for col, definition in [("description", "TEXT"), ("evidence_passage_id", "TEXT"), ("doc_id", "TEXT"), ("note", "TEXT"), ("confidence", "TEXT")]:
            add_col("relationships", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS mentions (mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, doc_id TEXT NOT NULL, passage_id TEXT NOT NULL, surface_form TEXT NOT NULL, char_start INTEGER, char_end INTEGER, status TEXT NOT NULL DEFAULT 'verified', note TEXT, created_at TEXT NOT NULL)")

        if conn.execute("SELECT COUNT(*) FROM taxonomy_profiles").fetchone()[0] == 0:
            conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)", ("General DH Profile", "Default categories", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for name, desc in DEFAULT_CATEGORIES:
                conn.execute("INSERT INTO entity_categories (profile_id, name, description, is_default) VALUES (?, ?, ?, 1)", (pid, name, desc))
            for name, desc, directed in DEFAULT_RELATIONSHIP_TYPES:
                conn.execute("INSERT INTO relationship_types (profile_id, name, description, directed, is_default) VALUES (?, ?, ?, ?, 1)", (pid, name, desc, directed))

        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(passage_id UNINDEXED, doc_id UNINDEXED, plain_text)")
        
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

def next_entity_id(conn) -> str:
    row = conn.execute("SELECT entity_id FROM entities WHERE entity_id LIKE 'ENT-%' ORDER BY entity_id DESC LIMIT 1").fetchone()
    num = 1 if row is None else int(row[0].split("-")[1]) + 1
    return f"ENT-{num:06d}"

def save_mention(conn, *, entity_id: str, doc_id: str, passage_id: str, surface_form: str, char_start: int, char_end: int, note: str | None = None) -> str:
    passage = conn.execute("SELECT plain_text FROM passages WHERE passage_id = ?", (passage_id,)).fetchone()
    if not passage:
        raise ValueError("Passage not found.")
    text = passage["plain_text"]
    if char_start < 0 or char_end > len(text) or char_start >= char_end:
        raise OffsetValidationError(f"Offsets ({char_start}, {char_end}) are out of bounds for passage length {len(text)}.")
    actual_surface = text[char_start:char_end]
    if actual_surface != surface_form:
        raise OffsetValidationError(f"Offset mismatch! Text at [{char_start}:{char_end}] is '{actual_surface}', but expected '{surface_form}'.")

    mention_id = f"MEN-{utc_now().replace('-', '').replace(':', '').replace('T', '')[:14]}"
    conn.execute("INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, utc_now()))
    return mention_id

def save_candidate(conn, *, doc_id: str, passage_id: str, surface_form: str, char_start: int, char_end: int, suggested_category_id: int | None = None, confidence_score: float = 0.0, recognition_method: str = "heuristic", contextual_evidence: str = "") -> int:
    conn.execute(
        "INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, utc_now())
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_candidates_paginated(conn, doc_id: str, limit: int = 10, offset: int = 0) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT c.*, p.plain_text as passage_text, cat.name as suggested_category_name "
        "FROM entity_candidates c JOIN passages p ON c.passage_id = p.passage_id "
        "LEFT JOIN entity_categories cat ON c.suggested_category_id = cat.category_id "
        "WHERE c.doc_id = ? AND c.review_status = 'pending' ORDER BY c.char_start LIMIT ? OFFSET ?",
        (doc_id, limit, offset)
    ).fetchall()

def count_candidates(conn, doc_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM entity_candidates WHERE doc_id = ? AND review_status = 'pending'", (doc_id,)).fetchone()[0]

def update_candidate_status(conn, candidate_id: int, status: str) -> None:
    conn.execute("UPDATE entity_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))

def list_documents(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT doc_id, title, original_filename, language, import_date, (SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) AS passage_count FROM documents d ORDER BY doc_id").fetchall()

def get_document(conn, doc_id: str) -> sqlite3.Row | None: return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
def get_passages(conn, doc_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
def get_passages_paginated(conn, doc_id: str, limit: int, offset: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
def count_passages(conn, doc_id: str) -> int: return conn.execute("SELECT COUNT(*) FROM passages WHERE doc_id = ?", (doc_id,)).fetchone()[0]

def get_all_passages(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM passages ORDER BY doc_id, sequence").fetchall()

def get_profiles(conn) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM taxonomy_profiles").fetchall()
def get_categories(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM entity_categories WHERE profile_id = ? ORDER BY name", (profile_id,)).fetchall()
def get_relationship_types(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM relationship_types WHERE profile_id = ?", (profile_id,)).fetchall()
def get_entities(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT e.*, c.name as category_name FROM entities e JOIN entity_categories c ON e.category_id = c.category_id WHERE e.profile_id = ? ORDER BY e.entity_id", (profile_id,)).fetchall()
def get_mentions_for_document(conn, doc_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM mentions WHERE doc_id = ? AND char_start IS NOT NULL", (doc_id,)).fetchall()
def get_attribute_definitions(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()
def get_attribute_values(conn, entity_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT av.*, ad.name FROM attribute_values av JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id WHERE av.entity_id = ?", (entity_id,)).fetchall()

def database_stats(conn) -> dict:
    tables = {"documents": "documents", "passages": "passages", "entities": "entities", "mentions": "mentions", "relationships": "relationships", "categories": "entity_categories"}
    return {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in tables.items()}
def bulk_save_candidates(conn, candidates: list[dict]) -> int:
    """Inserts multiple candidates in a single fast transaction."""
    if not candidates:
        return 0
        
    # To prevent duplicates, we only insert if the exact span doesn't already exist
    new_candidates = []
    for c in candidates:
        existing = conn.execute(
            "SELECT 1 FROM entity_candidates WHERE passage_id = ? AND char_start = ? AND char_end = ? AND review_status = 'pending'",
            (c["passage_id"], c["char_start"], c["char_end"])
        ).fetchone()
        if not existing:
            new_candidates.append((
                c["doc_id"], c["passage_id"], c["surface_form"], c["char_start"], c["char_end"], 
                c["suggested_category_id"], c["confidence_score"], c["recognition_method"], 
                c["contextual_evidence"], c["created_at"]
            ))
            
    if new_candidates:
        conn.executemany(
            "INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            new_candidates
        )
    return len(new_candidates)
# --- TAXONOMY IMPORT / EXPORT ---
def export_profile(conn, profile_id: int) -> dict:
    """Exports a taxonomy profile and all its rules to a Python dictionary."""
    profile = conn.execute("SELECT * FROM taxonomy_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
    if not profile: return {}
    
    cats = conn.execute("SELECT * FROM entity_categories WHERE profile_id = ?", (profile_id,)).fetchall()
    rels = conn.execute("SELECT * FROM relationship_types WHERE profile_id = ?", (profile_id,)).fetchall()
    attrs = conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()
    
    return {
        "profile": dict(profile),
        "categories": [dict(c) for c in cats],
        "relationships": [dict(r) for r in rels],
        "attributes": [dict(a) for a in attrs]
    }

def import_profile(conn, data: dict) -> int:
    """Imports a taxonomy profile from a dictionary, avoiding overwrites."""
    p_data = data.get("profile", {})
    p_name = p_data.get("name", "Imported Profile") + " (Copy)"
    
    # 1. Create new profile
    conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)", 
                 (p_name, p_data.get("description", ""), utc_now()))
    new_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # 2. Map old category IDs to new ones
    cat_map = {}
    for c in data.get("categories", []):
        conn.execute("INSERT INTO entity_categories (profile_id, name, description, color, icon, is_default) VALUES (?, ?, ?, ?, ?, ?)",
                     (new_pid, c.get("name"), c.get("description"), c.get("color"), c.get("icon"), c.get("is_default", 0)))
        cat_map[c["category_id"]] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
    # 3. Fix hierarchy (parent_ids)
    for c in data.get("categories", []):
        if c.get("parent_id") and c["parent_id"] in cat_map:
            new_parent_id = cat_map[c["parent_id"]]
            new_cat_id = cat_map[c["category_id"]]
            conn.execute("UPDATE entity_categories SET parent_id = ? WHERE category_id = ?", (new_parent_id, new_cat_id))

    # 4. Import Relationships
    for r in data.get("relationships", []):
        conn.execute("INSERT INTO relationship_types (profile_id, group_name, name, description, directed, is_default) VALUES (?, ?, ?, ?, ?, ?)",
                     (new_pid, r.get("group_name"), r.get("name"), r.get("description"), r.get("directed", 1), r.get("is_default", 0)))

    # 5. Import Attributes
    for a in data.get("attributes", []):
        new_cat_id = cat_map.get(a["category_id"]) if a.get("category_id") else None
        conn.execute("INSERT INTO attribute_definitions (profile_id, target_table, category_id, name, data_type, description) VALUES (?, ?, ?, ?, ?, ?)",
                     (new_pid, a.get("target_table"), new_cat_id, a.get("name"), a.get("data_type"), a.get("description")))
                     
    return new_pid
