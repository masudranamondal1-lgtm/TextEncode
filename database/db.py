"""SQLite persistence for TextEncode v0.5 (Projects, Corpora, Evidence)."""

from __future__ import annotations
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"
SCHEMA_VERSION = 5

class DuplicateDocumentError(Exception):
    def __init__(self, existing_doc_id: str):
        self.existing_doc_id = existing_doc_id
        super().__init__(f"This exact file has already been imported as {existing_doc_id}.")
class OffsetValidationError(Exception):
    def __init__(self, message: str): super().__init__(message)

DEFAULT_CATEGORIES = [("Person", "Individuals, historical figures and literary characters."), ("Plant", "Trees, shrubs, crops, flowers and other plant life."), ("Animal", "Animals, birds, fish, insects and other fauna."), ("Place", "Settlements, regions, buildings and geographical locations."), ("River or hydrological feature", "Rivers, tributaries, canals, wetlands and other water bodies."), ("Institution", "Formal or informal organisations and institutions."), ("Material object", "Physical objects, tools, artefacts and infrastructure."), ("Economic activity", "Occupations, production, exchange, trade and livelihood activities."), ("Event", "Historical, social, political, ecological or narrative events."), ("Cultural practice", "Rituals, customs, traditions and social practices."), ("Ecological entity", "Ecosystems, habitats and ecological formations."), ("Other", "Entities that do not fit the existing categories.")]
DEFAULT_RELATIONSHIP_TYPES = [("inhabits", "Source lives in or occupies target.", 1), ("depends_on", "Source relies on target for livelihood or survival.", 1), ("affects", "Source acts upon or influences target.", 1), ("uses", "Source makes practical use of target.", 1), ("owns", "Source holds target as property.", 1), ("controls", "Source exercises control over target.", 1), ("governs", "Source administers or rules target.", 1), ("trades_with", "Source exchanges goods or services with target.", 1), ("exploits", "Source extracts value from target.", 1), ("protects", "Source safeguards target.", 1), ("contests", "Source disputes, resists or competes with target.", 1), ("remembers", "Source commemorates or recalls target.", 1), ("represents", "Source stands for or symbolises target.", 1), ("transforms", "Source changes the state or form of target.", 1), ("connected_to", "General association; treat as undirected.", 0), ("other", "Any other relationship; describe it in the notes.", 1)]

def utc_now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")

@contextmanager
def get_connection(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA foreign_keys = ON")
    try: yield conn; conn.commit()
    except Exception: conn.rollback(); raise
    finally: conn.close()

def init_db(db_path: str | Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (project_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS corpora (corpus_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT, created_at TEXT NOT NULL);
            
            CREATE TABLE IF NOT EXISTS documents (doc_id TEXT PRIMARY KEY, corpus_id INTEGER REFERENCES corpora(corpus_id) ON DELETE CASCADE, title TEXT NOT NULL, original_filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE, language TEXT, author TEXT, publication_info TEXT, source_text TEXT NOT NULL, import_date TEXT NOT NULL, deleted_at TEXT DEFAULT NULL);
            CREATE TABLE IF NOT EXISTS passages (passage_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_type TEXT NOT NULL, sequence INTEGER NOT NULL, heading_level INTEGER, heading_path TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, plain_text TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, content_hash TEXT NOT NULL, UNIQUE (doc_id, sequence));
            
            CREATE TABLE IF NOT EXISTS taxonomy_profiles (profile_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attribute_definitions (attribute_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL, target_table TEXT NOT NULL, category_id INTEGER, name TEXT NOT NULL, data_type TEXT NOT NULL, description TEXT);
            CREATE TABLE IF NOT EXISTS attribute_values (value_id INTEGER PRIMARY KEY AUTOINCREMENT, attribute_id INTEGER NOT NULL, entity_id TEXT, relationship_id TEXT, value_text TEXT);
            CREATE TABLE IF NOT EXISTS entity_candidates (candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE, surface_form TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, suggested_category_id INTEGER REFERENCES entity_categories(category_id), confidence_score REAL DEFAULT 0.0, recognition_method TEXT, contextual_evidence TEXT, review_status TEXT DEFAULT 'pending', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT, record_type TEXT NOT NULL, record_id TEXT NOT NULL, operation TEXT NOT NULL, old_value TEXT, new_value TEXT, timestamp TEXT NOT NULL, origin TEXT NOT NULL);
            
            CREATE TABLE IF NOT EXISTS evidence_bundles (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id) ON DELETE CASCADE,
                evidence_domain TEXT NOT NULL CHECK(evidence_domain IN ('Literary', 'Historical', 'Geographical')),
                source_text TEXT NOT NULL,
                context TEXT,
                created_at TEXT NOT NULL
            );
        """)
        
        def add_col(table, col, definition):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

        add_col("mentions", "deleted_at", "TEXT DEFAULT NULL")
        
        conn.execute("CREATE TABLE IF NOT EXISTS entity_categories (category_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("parent_id", "INTEGER"), ("description", "TEXT"), ("color", "TEXT DEFAULT '#808080'"), ("icon", "TEXT DEFAULT '📦'"), ("is_default", "INTEGER NOT NULL DEFAULT 0")]: add_col("entity_categories", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS relationship_types (type_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("group_name", "TEXT DEFAULT 'General'"), ("description", "TEXT"), ("directed", "INTEGER NOT NULL DEFAULT 1"), ("is_default", "INTEGER NOT NULL DEFAULT 0")]: add_col("relationship_types", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, category_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        for col, definition in [("profile_id", "INTEGER DEFAULT 1"), ("alt_names", "TEXT"), ("transliteration", "TEXT"), ("description", "TEXT"), ("notes", "TEXT"), ("doc_id", "TEXT"), ("latitude", "REAL"), ("longitude", "REAL"), ("geometry_type", "TEXT DEFAULT 'Point'"), ("location_status", "TEXT DEFAULT 'Uncertain'"), ("deleted_at", "TEXT DEFAULT NULL")]: add_col("entities", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS relationships (relationship_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL, type_id INTEGER NOT NULL, created_at TEXT NOT NULL)")
        for col, definition in [("description", "TEXT"), ("evidence_passage_id", "TEXT"), ("doc_id", "TEXT"), ("note", "TEXT"), ("confidence", "TEXT"), ("deleted_at", "TEXT DEFAULT NULL")]: add_col("relationships", col, definition)

        conn.execute("CREATE TABLE IF NOT EXISTS mentions (mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, doc_id TEXT NOT NULL, passage_id TEXT NOT NULL, surface_form TEXT NOT NULL, char_start INTEGER, char_end INTEGER, status TEXT NOT NULL DEFAULT 'verified', note TEXT, created_at TEXT NOT NULL, deleted_at TEXT DEFAULT NULL)")

        if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            conn.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)", ("Default Project", "Automatically created.", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO corpora (project_id, name, description, created_at) VALUES (?, ?, ?, ?)", (pid, "Default Corpus", "Automatically created.", utc_now()))
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE documents SET corpus_id = ? WHERE corpus_id IS NULL", (cid,))

        if conn.execute("SELECT COUNT(*) FROM taxonomy_profiles").fetchone()[0] == 0:
            conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)", ("General DH Profile", "Default categories", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for name, desc in DEFAULT_CATEGORIES: conn.execute("INSERT INTO entity_categories (profile_id, name, description, is_default) VALUES (?, ?, ?, 1)", (pid, name, desc))
            for name, desc, directed in DEFAULT_RELATIONSHIP_TYPES: conn.execute("INSERT INTO relationship_types (profile_id, name, description, directed, is_default) VALUES (?, ?, ?, ?, 1)", (pid, name, desc, directed))

        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(passage_id UNINDEXED, doc_id UNINDEXED, plain_text)")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

# --- PROJECTS & CORPORA ---
def get_projects(conn) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM projects ORDER BY project_id").fetchall()
def create_project(conn, name: str, description: str) -> int:
    conn.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)", (name, description, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def get_corpora(conn, project_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM corpora WHERE project_id = ?", (project_id,)).fetchall()
def create_corpus(conn, project_id: int, name: str, description: str) -> int:
    conn.execute("INSERT INTO corpora (project_id, name, description, created_at) VALUES (?, ?, ?, ?)", (project_id, name, description, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def next_entity_id(conn) -> str:
    row = conn.execute("SELECT entity_id FROM entities WHERE entity_id LIKE 'ENT-%' ORDER BY entity_id DESC LIMIT 1").fetchone()
    num = 1 if row is None else int(row[0].split("-")[1]) + 1
    return f"ENT-{num:06d}"

def save_mention(conn, *, entity_id: str, doc_id: str, passage_id: str, surface_form: str, char_start: int, char_end: int, note: str | None = None) -> str:
    passage = conn.execute("SELECT plain_text FROM passages WHERE passage_id = ?", (passage_id,)).fetchone()
    if not passage: raise ValueError("Passage not found.")
    text = passage["plain_text"]
    if char_start < 0 or char_end > len(text) or char_start >= char_end: raise OffsetValidationError(f"Offsets out of bounds.")
    actual_surface = text[char_start:char_end]
    if actual_surface != surface_form: raise OffsetValidationError(f"Offset mismatch! Text at [{char_start}:{char_end}] is '{actual_surface}', expected '{surface_form}'.")
    mention_id = f"MEN-{utc_now().replace('-', '').replace(':', '').replace('T', '')[:14]}"
    conn.execute("INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, utc_now()))
    return mention_id

def save_candidate(conn, *, doc_id: str, passage_id: str, surface_form: str, char_start: int, char_end: int, suggested_category_id: int | None = None, confidence_score: float = 0.0, recognition_method: str = "heuristic", contextual_evidence: str = "") -> int:
    conn.execute("INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def get_candidates_paginated(conn, doc_id: str, limit: int = 10, offset: int = 0) -> list[sqlite3.Row]:
    return conn.execute("SELECT c.*, p.plain_text as passage_text, cat.name as suggested_category_name FROM entity_candidates c JOIN passages p ON c.passage_id = p.passage_id LEFT JOIN entity_categories cat ON c.suggested_category_id = cat.category_id WHERE c.doc_id = ? AND c.review_status = 'pending' ORDER BY c.char_start LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()

def count_candidates(conn, doc_id: str) -> int: return conn.execute("SELECT COUNT(*) FROM entity_candidates WHERE doc_id = ? AND review_status = 'pending'", (doc_id,)).fetchone()[0]
def update_candidate_status(conn, candidate_id: int, status: str) -> None: conn.execute("UPDATE entity_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))

def list_documents(conn, corpus_id: int | None = None, include_deleted=False) -> list[sqlite3.Row]:
    query = "SELECT doc_id, title, original_filename, language, author, publication_info, import_date, deleted_at, corpus_id, (SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) AS passage_count FROM documents d WHERE 1=1"
    params = []
    if not include_deleted: query += " AND deleted_at IS NULL"
    if corpus_id: query += " AND corpus_id = ?"; params.append(corpus_id)
    query += " ORDER BY doc_id"
    return conn.execute(query, params).fetchall()

def update_document_metadata(conn, doc_id: str, title: str, author: str, language: str, publication_info: str) -> None:
    conn.execute("UPDATE documents SET title = ?, author = ?, language = ?, publication_info = ? WHERE doc_id = ?", (title, author, language, publication_info, doc_id))

def soft_delete_document(conn, doc_id: str) -> None: conn.execute("UPDATE documents SET deleted_at = ? WHERE doc_id = ?", (utc_now(), doc_id))
def restore_document(conn, doc_id: str) -> None: conn.execute("UPDATE documents SET deleted_at = NULL WHERE doc_id = ?", (doc_id,))
def permanent_delete_document(conn, doc_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM passage_search WHERE doc_id = ?", (doc_id,))

def get_document(conn, doc_id: str) -> sqlite3.Row | None: return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
def get_passages(conn, doc_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
def get_passages_paginated(conn, doc_id: str, limit: int, offset: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
def count_passages(conn, doc_id: str) -> int: return conn.execute("SELECT COUNT(*) FROM passages WHERE doc_id = ?", (doc_id,)).fetchone()[0]
def get_all_passages(conn) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM passages WHERE doc_id IN (SELECT doc_id FROM documents WHERE deleted_at IS NULL)").fetchall()
def get_profiles(conn) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM taxonomy_profiles").fetchall()
def get_categories(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM entity_categories WHERE profile_id = ? ORDER BY name", (profile_id,)).fetchall()
def get_relationship_types(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM relationship_types WHERE profile_id = ?", (profile_id,)).fetchall()
def get_entities(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT e.*, c.name as category_name FROM entities e JOIN entity_categories c ON e.category_id = c.category_id WHERE e.profile_id = ? AND e.deleted_at IS NULL ORDER BY e.entity_id", (profile_id,)).fetchall()

def get_all_entities_with_stats(conn, profile_id: int) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT e.entity_id, e.canonical_name, e.alt_names, e.description, c.name as category_name, COUNT(m.mention_id) as mention_count
        FROM entities e JOIN entity_categories c ON e.category_id = c.category_id 
        LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.deleted_at IS NULL
        WHERE e.profile_id = ? AND e.deleted_at IS NULL GROUP BY e.entity_id ORDER BY mention_count DESC, e.entity_id
    """, (profile_id,)).fetchall()

def update_entity_details(conn, entity_id: str, canonical_name: str, category_id: int, alt_names: str, description: str) -> None:
    conn.execute("UPDATE entities SET canonical_name = ?, category_id = ?, alt_names = ?, description = ? WHERE entity_id = ?", (canonical_name, category_id, alt_names, description, entity_id))

def soft_delete_entity(conn, entity_id: str) -> None: conn.execute("UPDATE entities SET deleted_at = ? WHERE entity_id = ?", (utc_now(), entity_id))
def restore_entity(conn, entity_id: str) -> None: conn.execute("UPDATE entities SET deleted_at = NULL WHERE entity_id = ?", (entity_id,))

def get_mentions_for_entity(conn, entity_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT m.mention_id, m.surface_form, m.char_start, m.char_end, p.passage_id, p.plain_text FROM mentions m JOIN passages p ON m.passage_id = p.passage_id WHERE m.entity_id = ? AND m.deleted_at IS NULL", (entity_id,)).fetchall()

def delete_mention(conn, mention_id: str) -> None: conn.execute("UPDATE mentions SET deleted_at = ? WHERE mention_id = ?", (utc_now(), mention_id))

def get_relationships(conn) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT r.relationship_id, r.source_entity_id, r.target_entity_id, 
               s.canonical_name as source_name, t.canonical_name as target_name, 
               rt.name as type_name, r.description
        FROM relationships r
        JOIN entities s ON r.source_entity_id = s.entity_id
        JOIN entities t ON r.target_entity_id = t.entity_id
        JOIN relationship_types rt ON r.type_id = rt.type_id
        WHERE r.deleted_at IS NULL
    """).fetchall()

def update_relationship(conn, rel_id: str, source_id: str, target_id: str, type_id: int, description: str) -> None:
    conn.execute("UPDATE relationships SET source_entity_id = ?, target_entity_id = ?, type_id = ?, description = ? WHERE relationship_id = ?", (source_id, target_id, type_id, description, rel_id))

def save_relationship(conn, source_id: str, target_id: str, type_id: int, description: str) -> None:
    rel_id = f"REL-{utc_now().replace('-', '').replace(':', '').replace('T', '')[:14]}"
    conn.execute("INSERT INTO relationships (relationship_id, source_entity_id, target_entity_id, type_id, description, created_at) VALUES (?, ?, ?, ?, ?, ?)", (rel_id, source_id, target_id, type_id, description, utc_now()))

def delete_relationship(conn, rel_id: str) -> None: conn.execute("DELETE FROM relationships WHERE relationship_id = ?", (rel_id,))

# --- EVIDENCE BUNDLES ---
def get_evidence_for_relationship(conn, rel_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM evidence_bundles WHERE relationship_id = ? ORDER BY evidence_id", (rel_id,)).fetchall()

def add_evidence_bundle(conn, rel_id: str, domain: str, source_text: str, context: str) -> int:
    conn.execute("INSERT INTO evidence_bundles (relationship_id, evidence_domain, source_text, context, created_at) VALUES (?, ?, ?, ?, ?)", (rel_id, domain, source_text, context, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def delete_evidence_bundle(conn, evidence_id: int) -> None:
    conn.execute("DELETE FROM evidence_bundles WHERE evidence_id = ?", (evidence_id,))

def get_mentions_for_document(conn, doc_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM mentions WHERE doc_id = ? AND char_start IS NOT NULL AND deleted_at IS NULL", (doc_id,)).fetchall()
def get_attribute_definitions(conn, profile_id: int) -> list[sqlite3.Row]: return conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()
def get_attribute_values(conn, entity_id: str) -> list[sqlite3.Row]: return conn.execute("SELECT av.*, ad.name FROM attribute_values av JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id WHERE av.entity_id = ?", (entity_id,)).fetchall()

def database_stats(conn) -> dict:
    tables = {"documents": "documents WHERE deleted_at IS NULL", "passages": "passages", "entities": "entities WHERE deleted_at IS NULL", "mentions": "mentions WHERE deleted_at IS NULL", "relationships": "relationships WHERE deleted_at IS NULL", "categories": "entity_categories"}
    return {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in tables.items()}

def bulk_save_candidates(conn, candidates: list[dict]) -> int:
    if not candidates: return 0
    new_candidates = []
    for c in candidates:
        existing = conn.execute("SELECT 1 FROM entity_candidates WHERE passage_id = ? AND char_start = ? AND char_end = ? AND review_status = 'pending'", (c["passage_id"], c["char_start"], c["char_end"])).fetchone()
        if not existing:
            new_candidates.append((c["doc_id"], c["passage_id"], c["surface_form"], c["char_start"], c["char_end"], c["suggested_category_id"], c["confidence_score"], c["recognition_method"], c["contextual_evidence"], c["created_at"]))
    if new_candidates: conn.executemany("INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", new_candidates)
    return len(new_candidates)

def export_profile(conn, profile_id: int) -> dict:
    profile = conn.execute("SELECT * FROM taxonomy_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
    if not profile: return {}
    cats = conn.execute("SELECT * FROM entity_categories WHERE profile_id = ?", (profile_id,)).fetchall()
    rels = conn.execute("SELECT * FROM relationship_types WHERE profile_id = ?", (profile_id,)).fetchall()
    attrs = conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()
    return {"profile": dict(profile), "categories": [dict(c) for c in cats], "relationships": [dict(r) for r in rels], "attributes": [dict(a) for a in attrs]}

def import_profile(conn, data: dict) -> int:
    p_data = data.get("profile", {})
    p_name = p_data.get("name", "Imported Profile") + " (Copy)"
    conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)", (p_name, p_data.get("description", ""), utc_now()))
    new_pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    cat_map = {}
    for c in data.get("categories", []):
        conn.execute("INSERT INTO entity_categories (profile_id, name, description, color, icon, is_default) VALUES (?, ?, ?, ?, ?, ?)", (new_pid, c.get("name"), c.get("description"), c.get("color"), c.get("icon"), c.get("is_default", 0)))
        cat_map[c["category_id"]] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for c in data.get("categories", []):
        if c.get("parent_id") and c["parent_id"] in cat_map: conn.execute("UPDATE entity_categories SET parent_id = ? WHERE category_id = ?", (cat_map[c["parent_id"]], cat_map[c["category_id"]]))
    for r in data.get("relationships", []):
        conn.execute("INSERT INTO relationship_types (profile_id, group_name, name, description, directed, is_default) VALUES (?, ?, ?, ?, ?, ?)", (new_pid, r.get("group_name"), r.get("name"), r.get("description"), r.get("directed", 1), r.get("is_default", 0)))
    for a in data.get("attributes", []):
        new_cat_id = cat_map.get(a["category_id"]) if a.get("category_id") else None
        conn.execute("INSERT INTO attribute_definitions (profile_id, target_table, category_id, name, data_type, description) VALUES (?, ?, ?, ?, ?, ?)", (new_pid, a.get("target_table"), new_cat_id, a.get("name"), a.get("data_type"), a.get("description")))
    return new_pid

def save_document(conn, *, title: str, original_filename: str, source_text: str, passages: list[dict], language: str | None = None, author: str | None = None, publication_info: str | None = None, corpus_id: int | None = None) -> str:
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    existing = conn.execute("SELECT doc_id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
    if existing is not None: raise DuplicateDocumentError(existing["doc_id"])
    doc_id = f"DOC-{conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0] + 1:03d}"
    conn.execute("INSERT INTO documents (doc_id, corpus_id, title, original_filename, file_hash, language, author, publication_info, source_text, import_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (doc_id, corpus_id, title, original_filename, file_hash, language, author, publication_info, source_text, utc_now()))
    rows, search_rows = [], []
    for seq, p in enumerate(passages, start=1):
        pid = f"{doc_id}-P{seq:03d}"
        rows.append((pid, doc_id, p["passage_type"], seq, p.get("heading_level"), p.get("heading_path") or "", p["text"], p["plain_text"], p["char_start"], p["char_end"], p["content_hash"]))
        search_rows.append((pid, doc_id, p["plain_text"]))
    conn.executemany("INSERT INTO passages (passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO passage_search (passage_id, doc_id, plain_text) VALUES (?, ?, ?)", search_rows)
    return doc_id

def search_passages_fts(conn, query: str, doc_id: str | None = None) -> list[sqlite3.Row]:
    if doc_id: return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? AND p.doc_id = ? ORDER BY rank", (query, doc_id)).fetchall()
    return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? ORDER BY rank", (query,)).fetchall()
