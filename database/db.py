"""SQLite persistence for TextEncode v0.6."""
from __future__ import annotations
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"
SCHEMA_VERSION = 6

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

def create_safe_backup(db_path: str | Path | None = None) -> str:
    source_path = Path(db_path) if db_path is not None else DB_PATH
    if not source_path.is_file():
        raise FileNotFoundError(f"Database file not found: {source_path}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = source_path.parent / f"{source_path.stem}_backup_{timestamp}{source_path.suffix or '.db'}"
    source = destination = None
    try:
        source = sqlite3.connect(str(source_path), timeout=30)
        destination = sqlite3.connect(str(backup_path), timeout=30)
        source.backup(destination)
        check = destination.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {check[0] if check else 'no result'}")
        destination.commit()
    except Exception:
        if destination is not None:
            destination.close(); destination = None
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    return str(backup_path)

@contextmanager
def get_connection(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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
            CREATE TABLE IF NOT EXISTS projects (project_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS corpora (corpus_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (doc_id TEXT PRIMARY KEY, corpus_id INTEGER REFERENCES corpora(corpus_id) ON DELETE SET NULL, title TEXT NOT NULL, original_filename TEXT NOT NULL, file_hash TEXT NOT NULL UNIQUE, language TEXT, author TEXT, publication_info TEXT, source_text TEXT NOT NULL, import_date TEXT NOT NULL, deleted_at TEXT DEFAULT NULL);
            CREATE TABLE IF NOT EXISTS passages (passage_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_type TEXT NOT NULL, sequence INTEGER NOT NULL, heading_level INTEGER, heading_path TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, plain_text TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, content_hash TEXT NOT NULL, UNIQUE (doc_id, sequence));
            CREATE TABLE IF NOT EXISTS taxonomy_profiles (profile_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entity_categories (category_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL REFERENCES taxonomy_profiles(profile_id) ON DELETE CASCADE, parent_id INTEGER REFERENCES entity_categories(category_id) ON DELETE SET NULL, name TEXT NOT NULL, description TEXT, color TEXT DEFAULT '#808080', icon TEXT DEFAULT '📦', is_default INTEGER NOT NULL DEFAULT 0, UNIQUE(profile_id, name));
            CREATE TABLE IF NOT EXISTS relationship_types (type_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL REFERENCES taxonomy_profiles(profile_id) ON DELETE CASCADE, group_name TEXT DEFAULT 'General', name TEXT NOT NULL, description TEXT, directed INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0, UNIQUE(profile_id, name));
            CREATE TABLE IF NOT EXISTS attribute_definitions (attribute_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL REFERENCES taxonomy_profiles(profile_id) ON DELETE CASCADE, target_table TEXT NOT NULL, category_id INTEGER, name TEXT NOT NULL, data_type TEXT NOT NULL, description TEXT);
            CREATE TABLE IF NOT EXISTS entities (entity_id TEXT PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES taxonomy_profiles(profile_id), canonical_name TEXT NOT NULL, category_id INTEGER NOT NULL REFERENCES entity_categories(category_id), alt_names TEXT, transliteration TEXT, description TEXT, notes TEXT, doc_id TEXT, latitude REAL, longitude REAL, geometry_type TEXT DEFAULT 'Point', location_status TEXT DEFAULT 'Uncertain', deleted_at TEXT DEFAULT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS relationships (relationship_id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, target_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, type_id INTEGER NOT NULL REFERENCES relationship_types(type_id), description TEXT, evidence_passage_id TEXT, doc_id TEXT, note TEXT, confidence TEXT, deleted_at TEXT DEFAULT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mentions (mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE, surface_form TEXT NOT NULL, char_start INTEGER, char_end INTEGER, status TEXT NOT NULL DEFAULT 'verified', note TEXT, created_at TEXT NOT NULL, deleted_at TEXT DEFAULT NULL);
            CREATE TABLE IF NOT EXISTS evidence_bundles (evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id) ON DELETE CASCADE, evidence_domain TEXT NOT NULL, source_text TEXT NOT NULL, context TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entity_candidates (candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE, passage_id TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE, surface_form TEXT NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL, suggested_category_id INTEGER REFERENCES entity_categories(category_id), confidence_score REAL DEFAULT 0.0, recognition_method TEXT, contextual_evidence TEXT, review_status TEXT DEFAULT 'pending', created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT, record_type TEXT NOT NULL, record_id TEXT NOT NULL, operation TEXT NOT NULL, old_value TEXT, new_value TEXT, timestamp TEXT NOT NULL, origin TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS external_authorities (authority_id INTEGER PRIMARY KEY AUTOINCREMENT, provider_name TEXT NOT NULL UNIQUE, namespace TEXT NOT NULL, base_uri TEXT, enabled INTEGER DEFAULT 1, attribution TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entity_identifiers (identifier_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, authority_id INTEGER NOT NULL REFERENCES external_authorities(authority_id), external_identifier TEXT NOT NULL, external_uri TEXT, external_label TEXT, match_status TEXT DEFAULT 'accepted', researcher_note TEXT, accepted_at TEXT, UNIQUE(entity_id, authority_id, external_identifier));
            CREATE TABLE IF NOT EXISTS reconciliation_candidates (candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, authority_id INTEGER NOT NULL REFERENCES external_authorities(authority_id), external_identifier TEXT NOT NULL, external_uri TEXT, external_label TEXT, external_description TEXT, alternative_names TEXT, search_query TEXT, review_status TEXT DEFAULT 'suggested', created_at TEXT NOT NULL);
        """)

        def add_col(table, col, definition):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

        add_col("documents", "corpus_id", "INTEGER REFERENCES corpora(corpus_id) ON DELETE SET NULL")
        add_col("documents", "deleted_at", "TEXT DEFAULT NULL")
        add_col("mentions", "deleted_at", "TEXT DEFAULT NULL")
        # Phase 3 — structured evidence + soft delete
        for col, defn in {
            "source_type": "TEXT", "source_identifier": "TEXT", "author": "TEXT",
            "source_title": "TEXT", "publisher": "TEXT", "publication_year": "TEXT",
            "page_reference": "TEXT", "url": "TEXT", "access_date": "TEXT",
            "verification_status": "TEXT DEFAULT 'unverified'", "researcher_note": "TEXT",
            "deleted_at": "TEXT DEFAULT NULL",
        }.items():
            add_col("evidence_bundles", col, defn)
        # Phase 4 — relationship assessment, geometry, project/corpus/profile soft delete
        add_col("relationships", "research_assessment", "TEXT DEFAULT 'unassessed'")
        add_col("entities", "geometry_json", "TEXT")
        add_col("projects", "deleted_at", "TEXT DEFAULT NULL")
        add_col("projects", "updated_at", "TEXT")
        add_col("corpora", "deleted_at", "TEXT DEFAULT NULL")
        add_col("taxonomy_profiles", "deleted_at", "TEXT DEFAULT NULL")

        if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            conn.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)",
                         ("Default Project", "Automatically created.", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO corpora (project_id, name, description, created_at) VALUES (?, ?, ?, ?)",
                         (pid, "Default Corpus", "Automatically created.", utc_now()))
            cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE documents SET corpus_id = ? WHERE corpus_id IS NULL", (cid,))

        if conn.execute("SELECT COUNT(*) FROM taxonomy_profiles").fetchone()[0] == 0:
            conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?, ?, ?)",
                         ("General DH Profile", "Default categories", utc_now()))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            for name, desc in DEFAULT_CATEGORIES:
                conn.execute("INSERT INTO entity_categories (profile_id, name, description, is_default) VALUES (?, ?, ?, 1)", (pid, name, desc))
            for name, desc, directed in DEFAULT_RELATIONSHIP_TYPES:
                conn.execute("INSERT INTO relationship_types (profile_id, name, description, directed, is_default) VALUES (?, ?, ?, ?, 1)", (pid, name, desc, directed))

        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(passage_id UNINDEXED, doc_id UNINDEXED, plain_text, tokenize='unicode61')")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

def log_audit(conn, record_type, record_id, operation, old_value=None, new_value=None, origin="ui"):
    conn.execute(
        "INSERT INTO audit_log (record_type, record_id, operation, old_value, new_value, timestamp, origin) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (record_type, record_id, operation, old_value, new_value, utc_now(), origin))

def _next_sequential_id(conn, table, column, prefix, width) -> str:
    row = conn.execute(f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1", (f"{prefix}-%",)).fetchone()
    number = 1 if row is None else int(row[0].split("-")[1]) + 1
    return f"{prefix}-{number:0{width}d}"

def next_doc_id(conn): return _next_sequential_id(conn, "documents", "doc_id", "DOC", 3)
def next_entity_id(conn): return _next_sequential_id(conn, "entities", "entity_id", "ENT", 6)
def next_mention_id(conn): return f"MEN-{uuid.uuid4().hex[:8].upper()}"
def next_relationship_id(conn): return f"REL-{uuid.uuid4().hex[:8].upper()}"

def save_document(conn, *, title, original_filename, source_text, passages, language=None, author=None, publication_info=None, corpus_id=None) -> str:
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    existing = conn.execute("SELECT doc_id FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()
    if existing is not None:
        raise DuplicateDocumentError(existing["doc_id"])
    doc_id = next_doc_id(conn)
    conn.execute("INSERT INTO documents (doc_id, corpus_id, title, original_filename, file_hash, language, author, publication_info, source_text, import_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (doc_id, corpus_id, title, original_filename, file_hash, language, author, publication_info, source_text, utc_now()))
    rows, search_rows = [], []
    for seq, p in enumerate(passages, start=1):
        pid = f"{doc_id}-P{seq:03d}"
        rows.append((pid, doc_id, p["passage_type"], seq, p.get("heading_level"), p.get("heading_path") or "", p["text"], p["plain_text"], p["char_start"], p["char_end"], p["content_hash"]))
        search_rows.append((pid, doc_id, p["plain_text"]))
    conn.executemany("INSERT INTO passages (passage_id, doc_id, passage_type, sequence, heading_level, heading_path, text, plain_text, char_start, char_end, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO passage_search (passage_id, doc_id, plain_text) VALUES (?, ?, ?)", search_rows)
    return doc_id

def get_projects(conn): return conn.execute("SELECT * FROM projects ORDER BY project_id").fetchall()
def create_project(conn, name, description):
    conn.execute("INSERT INTO projects (name, description, created_at) VALUES (?, ?, ?)", (name, description, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def get_corpora(conn, project_id, include_deleted=False):
    q = "SELECT * FROM corpora WHERE project_id=?" + ("" if include_deleted else " AND deleted_at IS NULL") + " ORDER BY corpus_id"
    return conn.execute(q, (project_id,)).fetchall()
def create_corpus(conn, project_id, name, description):
    conn.execute("INSERT INTO corpora (project_id, name, description, created_at) VALUES (?, ?, ?, ?)", (project_id, name, description, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

def save_mention(conn, *, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note=None) -> str:
    passage = conn.execute("SELECT plain_text FROM passages WHERE passage_id = ?", (passage_id,)).fetchone()
    if not passage:
        raise ValueError("Passage not found.")
    text = passage["plain_text"]
    if char_start < 0 or char_end > len(text) or char_start >= char_end:
        raise OffsetValidationError("Offsets out of bounds.")
    actual_surface = text[char_start:char_end]
    if actual_surface != surface_form:
        raise OffsetValidationError(f"Offset mismatch! Text at [{char_start}:{char_end}] is '{actual_surface}', expected '{surface_form}'.")
    mention_id = next_mention_id(conn)
    conn.execute("INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (mention_id, entity_id, doc_id, passage_id, surface_form, char_start, char_end, note, utc_now()))
    return mention_id

def get_mentions_for_document(conn, doc_id): return conn.execute("SELECT * FROM mentions WHERE doc_id = ? AND char_start IS NOT NULL AND deleted_at IS NULL", (doc_id,)).fetchall()
def get_candidates_paginated(conn, doc_id, limit=10, offset=0):
    return conn.execute("SELECT c.*, p.plain_text as passage_text, cat.name as suggested_category_name FROM entity_candidates c JOIN passages p ON c.passage_id = p.passage_id LEFT JOIN entity_categories cat ON c.suggested_category_id = cat.category_id WHERE c.doc_id = ? AND c.review_status = 'pending' ORDER BY c.char_start LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
def count_candidates(conn, doc_id): return conn.execute("SELECT COUNT(*) FROM entity_candidates WHERE doc_id = ? AND review_status = 'pending'", (doc_id,)).fetchone()[0]
def update_candidate_status(conn, candidate_id, status):
    conn.execute("UPDATE entity_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))

def list_documents(conn, corpus_id=None, include_deleted=False):
    query = "SELECT doc_id, title, original_filename, language, author, publication_info, import_date, deleted_at, corpus_id, (SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) AS passage_count FROM documents d WHERE 1=1"
    params = []
    if not include_deleted: query += " AND deleted_at IS NULL"
    if corpus_id: query += " AND corpus_id = ?"; params.append(corpus_id)
    query += " ORDER BY doc_id"
    return conn.execute(query, params).fetchall()
def update_document_metadata(conn, doc_id, title, author, language, publication_info):
    conn.execute("UPDATE documents SET title = ?, author = ?, language = ?, publication_info = ? WHERE doc_id = ?", (title, author, language, publication_info, doc_id))
def soft_delete_document(conn, doc_id): conn.execute("UPDATE documents SET deleted_at = ? WHERE doc_id = ?", (utc_now(), doc_id))
def restore_document(conn, doc_id): conn.execute("UPDATE documents SET deleted_at = NULL WHERE doc_id = ?", (doc_id,))
def permanent_delete_document(conn, doc_id):
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM passage_search WHERE doc_id = ?", (doc_id,))
def delete_document(conn, doc_id): permanent_delete_document(conn, doc_id)
def get_document(conn, doc_id): return conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
def get_passages(conn, doc_id): return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
def get_passages_paginated(conn, doc_id, limit, offset): return conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
def count_passages(conn, doc_id): return conn.execute("SELECT COUNT(*) FROM passages WHERE doc_id = ?", (doc_id,)).fetchone()[0]

def get_profiles(conn): return conn.execute("SELECT * FROM taxonomy_profiles").fetchall()
def get_categories(conn, profile_id): return conn.execute("SELECT * FROM entity_categories WHERE profile_id = ? ORDER BY name", (profile_id,)).fetchall()
def get_relationship_types(conn, profile_id): return conn.execute("SELECT * FROM relationship_types WHERE profile_id = ?", (profile_id,)).fetchall()
def get_entities(conn, profile_id): return conn.execute("SELECT e.*, c.name as category_name FROM entities e JOIN entity_categories c ON e.category_id = c.category_id WHERE e.profile_id = ? AND e.deleted_at IS NULL ORDER BY e.entity_id", (profile_id,)).fetchall()
def get_all_entities_with_stats(conn, profile_id):
    return conn.execute("""
        SELECT e.entity_id, e.canonical_name, e.alt_names, e.description, c.name as category_name, COUNT(m.mention_id) as mention_count
        FROM entities e JOIN entity_categories c ON e.category_id = c.category_id
        LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.deleted_at IS NULL
        WHERE e.profile_id = ? AND e.deleted_at IS NULL GROUP BY e.entity_id ORDER BY mention_count DESC, e.entity_id
    """, (profile_id,)).fetchall()
def update_entity_details(conn, entity_id, canonical_name, category_id, alt_names, description):
    conn.execute("UPDATE entities SET canonical_name = ?, category_id = ?, alt_names = ?, description = ? WHERE entity_id = ?", (canonical_name, category_id, alt_names, description, entity_id))
def soft_delete_entity(conn, entity_id): conn.execute("UPDATE entities SET deleted_at = ? WHERE entity_id = ?", (utc_now(), entity_id))
def restore_entity(conn, entity_id): conn.execute("UPDATE entities SET deleted_at = NULL WHERE entity_id = ?", (entity_id,))
def get_mentions_for_entity(conn, entity_id):
    return conn.execute("SELECT m.mention_id, m.surface_form, m.char_start, m.char_end, p.passage_id, p.plain_text FROM mentions m JOIN passages p ON m.passage_id = p.passage_id WHERE m.entity_id = ? AND m.deleted_at IS NULL", (entity_id,)).fetchall()
def delete_mention(conn, mention_id): conn.execute("UPDATE mentions SET deleted_at = ? WHERE mention_id = ?", (utc_now(), mention_id))

def database_stats(conn):
    tables = {"documents": "documents WHERE deleted_at IS NULL", "passages": "passages",
              "entities": "entities WHERE deleted_at IS NULL", "mentions": "mentions WHERE deleted_at IS NULL",
              "relationships": "relationships WHERE deleted_at IS NULL", "categories": "entity_categories"}
    return {key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for key, table in tables.items()}

def bulk_save_candidates(conn, candidates):
    if not candidates: return 0
    new_candidates = []
    for c in candidates:
        existing = conn.execute("SELECT 1 FROM entity_candidates WHERE passage_id = ? AND char_start = ? AND char_end = ? AND review_status = 'pending'", (c["passage_id"], c["char_start"], c["char_end"])).fetchone()
        if not existing:
            new_candidates.append((c["doc_id"], c["passage_id"], c["surface_form"], c["char_start"], c["char_end"], c["suggested_category_id"], c["confidence_score"], c["recognition_method"], c["contextual_evidence"], c["created_at"]))
    if new_candidates:
        conn.executemany("INSERT INTO entity_candidates (doc_id, passage_id, surface_form, char_start, char_end, suggested_category_id, confidence_score, recognition_method, contextual_evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", new_candidates)
    return len(new_candidates)

def search_passages_fts(conn, query, doc_id=None):
    safe_query = f'"{query}"'
    if doc_id:
        return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? AND p.doc_id = ? ORDER BY rank", (safe_query, doc_id)).fetchall()
    return conn.execute("SELECT p.passage_id, p.doc_id, p.passage_type, p.plain_text, p.sequence, p.heading_path FROM passage_search f JOIN passages p ON f.passage_id = p.passage_id WHERE passage_search MATCH ? ORDER BY rank", (safe_query,)).fetchall()

# =====================================================================
# PHASE 4 — Projects, Corpora, Profiles, Geometry, Relationship scope
# =====================================================================
def update_project(conn, project_id, name, description):
    if not name.strip(): raise ValueError("Project name cannot be empty.")
    conn.execute("UPDATE projects SET name=?, description=?, updated_at=? WHERE project_id=?", (name.strip(), description.strip() or None, utc_now(), project_id))
    log_audit(conn, "projects", str(project_id), "updated", new_value=name.strip())

def duplicate_project(conn, project_id, new_name):
    src = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    if not src: raise ValueError("Source project not found.")
    new_id = create_project(conn, new_name.strip(), src["description"] or "")
    for c in conn.execute("SELECT name, description FROM corpora WHERE project_id=? AND deleted_at IS NULL", (project_id,)).fetchall():
        conn.execute("INSERT INTO corpora (project_id, name, description, created_at) VALUES (?, ?, ?, ?)", (new_id, c["name"], c["description"], utc_now()))
    log_audit(conn, "projects", str(new_id), "created", new_value=f"duplicate of {project_id}")
    return new_id

def soft_delete_project(conn, project_id):
    conn.execute("UPDATE projects SET deleted_at=? WHERE project_id=?", (utc_now(), project_id))
    log_audit(conn, "projects", str(project_id), "soft_deleted")
def restore_project(conn, project_id):
    conn.execute("UPDATE projects SET deleted_at=NULL WHERE project_id=?", (project_id,))
    log_audit(conn, "projects", str(project_id), "restored")
def hard_delete_project(conn, project_id):
    corpus_ids = [r["corpus_id"] for r in conn.execute("SELECT corpus_id FROM corpora WHERE project_id=?", (project_id,)).fetchall()]
    doc_ids = [r["doc_id"] for r in conn.execute(f"SELECT doc_id FROM documents WHERE corpus_id IN ({','.join('?'*len(corpus_ids)) or 'NULL'})", corpus_ids).fetchall()] if corpus_ids else []
    for d in doc_ids:
        conn.execute("DELETE FROM evidence_bundles WHERE relationship_id IN (SELECT relationship_id FROM relationships WHERE doc_id=?)", (d,))
        conn.execute("DELETE FROM relationships WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM entity_candidates WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM documents WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM passage_search WHERE doc_id=?", (d,))
    conn.execute("DELETE FROM corpora WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
    log_audit(conn, "projects", str(project_id), "hard_deleted", new_value=f"{len(corpus_ids)} corpora, {len(doc_ids)} docs")
def list_projects(conn, include_deleted=False):
    q = "SELECT * FROM projects" + ("" if include_deleted else " WHERE deleted_at IS NULL") + " ORDER BY project_id"
    return conn.execute(q).fetchall()

def update_corpus(conn, corpus_id, name, description):
    if not name.strip(): raise ValueError("Corpus name cannot be empty.")
    conn.execute("UPDATE corpora SET name=?, description=? WHERE corpus_id=?", (name.strip(), description.strip() or None, corpus_id))
def soft_delete_corpus(conn, corpus_id): conn.execute("UPDATE corpora SET deleted_at=? WHERE corpus_id=?", (utc_now(), corpus_id))
def restore_corpus(conn, corpus_id): conn.execute("UPDATE corpora SET deleted_at=NULL WHERE corpus_id=?", (corpus_id,))
def hard_delete_corpus(conn, corpus_id):
    doc_ids = [r["doc_id"] for r in conn.execute("SELECT doc_id FROM documents WHERE corpus_id=?", (corpus_id,)).fetchall()]
    for d in doc_ids:
        conn.execute("DELETE FROM evidence_bundles WHERE relationship_id IN (SELECT relationship_id FROM relationships WHERE doc_id=?)", (d,))
        conn.execute("DELETE FROM relationships WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM entity_candidates WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM documents WHERE doc_id=?", (d,))
        conn.execute("DELETE FROM passage_search WHERE doc_id=?", (d,))
    conn.execute("DELETE FROM corpora WHERE corpus_id=?", (corpus_id,))
def move_document_to_corpus(conn, doc_id, target_corpus_id):
    if not conn.execute("SELECT 1 FROM documents WHERE doc_id=? AND deleted_at IS NULL", (doc_id,)).fetchone():
        raise ValueError("Active document not found.")
    if not conn.execute("SELECT 1 FROM corpora WHERE corpus_id=? AND deleted_at IS NULL", (target_corpus_id,)).fetchone():
        raise ValueError("Target corpus not found.")
    conn.execute("UPDATE documents SET corpus_id=? WHERE doc_id=?", (target_corpus_id, doc_id))
    log_audit(conn, "documents", doc_id, "moved", new_value=f"corpus={target_corpus_id}")

def list_profiles(conn, include_deleted=False):
    q = "SELECT * FROM taxonomy_profiles" + ("" if include_deleted else " WHERE deleted_at IS NULL") + " ORDER BY profile_id"
    return conn.execute(q).fetchall()
def update_profile(conn, profile_id, name, description, is_active):
    if not name.strip(): raise ValueError("Profile name cannot be empty.")
    conn.execute("UPDATE taxonomy_profiles SET name=?, description=?, is_active=? WHERE profile_id=?", (name.strip(), description.strip() or None, int(is_active), profile_id))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "updated", new_value=name.strip())
def soft_delete_profile(conn, profile_id):
    conn.execute("UPDATE taxonomy_profiles SET deleted_at=?, is_active=0 WHERE profile_id=?", (utc_now(), profile_id))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "soft_deleted")
def restore_profile(conn, profile_id): conn.execute("UPDATE taxonomy_profiles SET deleted_at=NULL WHERE profile_id=?", (profile_id,))
def hard_delete_profile(conn, profile_id):
    if conn.execute("SELECT COUNT(*) FROM entities WHERE profile_id=?", (profile_id,)).fetchone()[0] > 0:
        raise ValueError("Cannot permanently delete a profile that still has entities. Soft-delete it instead.")
    conn.execute("DELETE FROM entity_categories WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM relationship_types WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM attribute_definitions WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM taxonomy_profiles WHERE profile_id=?", (profile_id,))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "hard_deleted")

def set_entity_geometry(conn, entity_id, geometry_type, geometry_json, latitude, longitude):
    conn.execute("UPDATE entities SET geometry_type=?, geometry_json=?, latitude=?, longitude=? WHERE entity_id=?", (geometry_type, geometry_json, latitude, longitude, entity_id))
    log_audit(conn, "entities", entity_id, "geometry_updated", new_value=geometry_type)

def list_relationships(conn, *, scope="doc", doc_id=None):
    base = """
        SELECT r.relationship_id, r.source_entity_id, r.target_entity_id,
               s.canonical_name AS source_name, t.canonical_name AS target_name,
               rt.name AS type_name, r.description, r.doc_id, r.confidence,
               r.research_assessment, r.note, r.created_at,
               (SELECT COUNT(*) FROM evidence_bundles e WHERE e.relationship_id = r.relationship_id AND e.deleted_at IS NULL) AS evidence_count
        FROM relationships r
        JOIN entities s ON s.entity_id = r.source_entity_id
        JOIN entities t ON t.entity_id = r.target_entity_id
        JOIN relationship_types rt ON rt.type_id = r.type_id
        WHERE r.deleted_at IS NULL
    """
    params = []
    if scope == "doc" and doc_id:
        base += " AND r.doc_id = ?"; params.append(doc_id)
    elif scope == "unassigned":
        base += " AND r.doc_id IS NULL"
    base += " ORDER BY r.created_at DESC"
    return conn.execute(base, params).fetchall()

def save_relationship(conn, source_id, target_id, type_id, description, doc_id=None, confidence=None, research_assessment="unassessed"):
    rel_id = next_relationship_id(conn)
    if confidence not in {"low", "medium", "high", None}:
        confidence = None
    conn.execute("INSERT INTO relationships (relationship_id, source_entity_id, target_entity_id, type_id, description, doc_id, confidence, research_assessment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (rel_id, source_id, target_id, type_id, description, doc_id, confidence, research_assessment, utc_now()))
    log_audit(conn, "relationships", rel_id, "created", new_value=f"{source_id}->{target_id} [{research_assessment}]")
    return rel_id
def update_relationship(conn, rel_id, source_id, target_id, type_id, description, doc_id=None, confidence=None, research_assessment="unassessed"):
    if source_id == target_id: raise ValueError("A relationship must connect two different entities.")
    if confidence not in {"low", "medium", "high", None}: confidence = None
    cur = conn.execute("UPDATE relationships SET source_entity_id=?, target_entity_id=?, type_id=?, description=?, doc_id=?, confidence=?, research_assessment=? WHERE relationship_id=? AND deleted_at IS NULL",
                       (source_id, target_id, type_id, description, doc_id, confidence, research_assessment, rel_id))
    if cur.rowcount != 1: raise ValueError(f"Active relationship not found: {rel_id}")
    log_audit(conn, "relationships", rel_id, "updated", new_value=f"doc_id={doc_id}, assessment={research_assessment}")
def soft_delete_relationship(conn, rel_id):
    cur = conn.execute("UPDATE relationships SET deleted_at=? WHERE relationship_id=? AND deleted_at IS NULL", (utc_now(), rel_id))
    if cur.rowcount != 1: raise ValueError(f"Active relationship not found: {rel_id}")
    log_audit(conn, "relationships", rel_id, "soft_deleted")
def restore_relationship(conn, rel_id):
    cur = conn.execute("UPDATE relationships SET deleted_at=NULL WHERE relationship_id=? AND deleted_at IS NOT NULL", (rel_id,))
    if cur.rowcount != 1: raise ValueError(f"Deleted relationship not found: {rel_id}")
    log_audit(conn, "relationships", rel_id, "restored")
def delete_relationship(conn, rel_id): conn.execute("DELETE FROM relationships WHERE relationship_id = ?", (rel_id,))

def get_evidence_for_relationship(conn, rel_id):
    return conn.execute("SELECT * FROM evidence_bundles WHERE relationship_id=? AND deleted_at IS NULL ORDER BY evidence_id", (rel_id,)).fetchall()
def add_evidence_bundle(conn, rel_id, domain, source_text, context="", *, source_type=None, source_identifier=None, author=None, source_title=None, publisher=None, publication_year=None, page_reference=None, url=None, access_date=None, verification_status="unverified", researcher_note=None):
    if not source_text or not source_text.strip(): raise ValueError("Evidence source text cannot be empty.")
    if verification_status not in {"unverified", "checked", "corroborated", "contested", "rejected"}:
        raise ValueError(f"Invalid verification status: {verification_status}")
    conn.execute("INSERT INTO evidence_bundles (relationship_id, evidence_domain, source_text, context, created_at, source_type, source_identifier, author, source_title, publisher, publication_year, page_reference, url, access_date, verification_status, researcher_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (rel_id, domain, source_text.strip(), context, utc_now(), source_type, source_identifier, author, source_title, publisher, publication_year, page_reference, url, access_date, verification_status, researcher_note))
    ev_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_audit(conn, "evidence_bundles", str(ev_id), "created", new_value=f"rel={rel_id}")
    return ev_id
def update_evidence_bundle(conn, evidence_id, **kwargs):
    allowed = {"evidence_domain", "source_text", "context", "source_type", "source_identifier", "author", "source_title", "publisher", "publication_year", "page_reference", "url", "access_date", "verification_status", "researcher_note"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates: return
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE evidence_bundles SET {sets} WHERE evidence_id=? AND deleted_at IS NULL", list(updates.values()) + [evidence_id])
    log_audit(conn, "evidence_bundles", str(evidence_id), "updated", new_value=str(updates))
def soft_delete_evidence(conn, evidence_id):
    conn.execute("UPDATE evidence_bundles SET deleted_at=? WHERE evidence_id=? AND deleted_at IS NULL", (utc_now(), evidence_id))
    log_audit(conn, "evidence_bundles", str(evidence_id), "soft_deleted")
def delete_evidence_bundle(conn, evidence_id): conn.execute("DELETE FROM evidence_bundles WHERE evidence_id = ?", (evidence_id,))

def save_category(conn, *, profile_id, name, description, parent_id=None):
    conn.execute("INSERT INTO entity_categories (profile_id, parent_id, name, description) VALUES (?, ?, ?, ?)", (profile_id, parent_id, name, description))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def save_relationship_type(conn, *, profile_id, group_name, name, description, directed):
    conn.execute("INSERT INTO relationship_types (profile_id, group_name, name, description, directed) VALUES (?, ?, ?, ?, ?)", (profile_id, group_name, name, description, directed))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def save_attribute_definition(conn, *, profile_id, target_table, category_id, name, data_type, description):
    conn.execute("INSERT INTO attribute_definitions (profile_id, target_table, category_id, name, data_type, description) VALUES (?, ?, ?, ?, ?, ?)", (profile_id, target_table, category_id, name, data_type, description))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def get_attribute_definitions(conn, profile_id): return conn.execute("SELECT * FROM attribute_definitions WHERE profile_id = ?", (profile_id,)).fetchall()

# =====================================================================
# PHASE 4 — Linked Data / External Authority Reconciliation
# =====================================================================
def init_external_authorities(conn):
    if conn.execute("SELECT COUNT(*) FROM external_authorities").fetchone()[0] == 0:
        now = utc_now()
        conn.execute("INSERT INTO external_authorities (provider_name, namespace, base_uri, enabled, attribution, created_at) VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)",
                     ("Wikidata", "wikidata", "http://www.wikidata.org/entity/", 1, "Wikidata is a free and open knowledge base.", now,
                      "GeoNames", "geonames", "http://sws.geonames.org/", 1, "GeoNames is a geographical database.", now))
def get_enabled_authorities(conn): return conn.execute("SELECT * FROM external_authorities WHERE enabled = 1").fetchall()
def add_entity_identifier(conn, entity_id, authority_id, external_identifier, external_uri, external_label, match_status="accepted", researcher_note=""):
    existing = conn.execute("SELECT identifier_id FROM entity_identifiers WHERE entity_id=? AND authority_id=? AND external_identifier=?", (entity_id, authority_id, external_identifier)).fetchone()
    if existing: return existing["identifier_id"]
    conn.execute("INSERT INTO entity_identifiers (entity_id, authority_id, external_identifier, external_uri, external_label, match_status, researcher_note, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (entity_id, authority_id, external_identifier, external_uri, external_label, match_status, researcher_note, utc_now()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def remove_entity_identifier(conn, identifier_id): conn.execute("DELETE FROM entity_identifiers WHERE identifier_id = ?", (identifier_id,))
def get_external_identifiers(conn, entity_id):
    return conn.execute("SELECT ei.*, ea.provider_name, ea.namespace FROM entity_identifiers ei JOIN external_authorities ea ON ei.authority_id = ea.authority_id WHERE ei.entity_id = ?", (entity_id,)).fetchall()
def save_reconciliation_candidates(conn, entity_id, authority_id, candidates, search_query):
    count = 0
    for c in candidates:
        existing = conn.execute("SELECT candidate_id FROM reconciliation_candidates WHERE entity_id=? AND external_identifier=? AND review_status='suggested'", (entity_id, c["external_identifier"])).fetchone()
        if not existing:
            conn.execute("INSERT INTO reconciliation_candidates (entity_id, authority_id, external_identifier, external_uri, external_label, external_description, alternative_names, search_query, review_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?)",
                         (entity_id, authority_id, c["external_identifier"], c["external_uri"], c["external_label"], c.get("external_description", ""), c.get("alternative_names", ""), search_query, utc_now()))
            count += 1
    return count
def get_candidates_for_entity(conn, entity_id, review_status="suggested"):
    return conn.execute("SELECT rc.*, ea.provider_name FROM reconciliation_candidates rc JOIN external_authorities ea ON rc.authority_id = ea.authority_id WHERE rc.entity_id = ? AND rc.review_status = ? ORDER BY rc.created_at DESC", (entity_id, review_status)).fetchall()
def update_reconciliation_candidate_status(conn, candidate_id, status):
    allowed = {"accepted", "rejected", "deferred", "superseded"}
    if status not in allowed: raise ValueError(f"Invalid status: {status}")
    conn.execute("UPDATE reconciliation_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))