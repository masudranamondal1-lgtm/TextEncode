"""SQLite persistence for TextEncode.

One module, one job: create the schema, generate stable IDs, and read/write
records. No parsing and no Streamlit code lives here, so everything in this
module is testable without a browser.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

#: Default database location: the project root (gitignored).
DB_PATH = Path(__file__).resolve().parent.parent / "textencode.db"

SCHEMA_VERSION = 1


class DuplicateDocumentError(Exception):
    """Raised when an identical file (same SHA-256) is imported again."""

    def __init__(self, existing_doc_id: str):
        self.existing_doc_id = existing_doc_id
        super().__init__(
            f"This exact file has already been imported as {existing_doc_id}. "
            "Identical files are not imported twice."
        )


#: The 12 default entity categories. Names live here (not scattered through
#: the UI) so they can be renamed or extended without touching app code.
DEFAULT_CATEGORIES = [
    ("Person", "Individuals, historical figures and literary characters."),
    ("Plant", "Trees, shrubs, crops, flowers and other plant life."),
    ("Animal", "Animals, birds, fish, insects and other fauna."),
    ("Place", "Settlements, regions, buildings and geographical locations."),
    ("River or hydrological feature",
     "Rivers, tributaries, canals, wetlands and other water bodies."),
    ("Institution", "Formal or informal organisations and institutions."),
    ("Material object", "Physical objects, tools, artefacts and infrastructure."),
    ("Economic activity",
     "Occupations, production, exchange, trade and livelihood activities."),
    ("Event", "Historical, social, political, ecological or narrative events."),
    ("Cultural practice", "Rituals, customs, traditions and social practices."),
    ("Ecological entity", "Ecosystems, habitats and ecological formations."),
    ("Other", "Entities that do not fit the existing categories."),
]

#: Default relationship types: (name, description, directed).
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
    doc_id            TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_hash         TEXT NOT NULL UNIQUE,
    language          TEXT,
    author            TEXT,
    publication_info  TEXT,
    source_text       TEXT NOT NULL,
    import_date       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passages (
    passage_id    TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    passage_type  TEXT NOT NULL CHECK (passage_type IN
                      ('heading','paragraph','list_item','blockquote','code_block')),
    sequence      INTEGER NOT NULL,
    heading_level INTEGER,
    heading_path  TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL,
    plain_text    TEXT NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,
    UNIQUE (doc_id, sequence),
    CHECK (char_end >= char_start),
    CHECK (char_start >= 0)
);
CREATE INDEX IF NOT EXISTS idx_passages_doc ON passages(doc_id);

CREATE TABLE IF NOT EXISTS entity_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    is_default  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    category_id     INTEGER NOT NULL
                    REFERENCES entity_categories(category_id),
    alt_names       TEXT,
    transliteration TEXT,
    description     TEXT,
    notes           TEXT,
    doc_id          TEXT REFERENCES documents(doc_id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category_id);

-- Mention offsets are RELATIVE TO passages.text, not to the whole document.
CREATE TABLE IF NOT EXISTS mentions (
    mention_id   TEXT PRIMARY KEY,
    entity_id    TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    passage_id   TEXT NOT NULL REFERENCES passages(passage_id) ON DELETE CASCADE,
    surface_form TEXT NOT NULL,
    char_start   INTEGER,
    char_end     INTEGER,
    status       TEXT NOT NULL DEFAULT 'verified'
                 CHECK (status IN ('suggested','verified','rejected')),
    note         TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE (entity_id, passage_id, char_start, char_end),
    CHECK (char_start IS NULL OR char_end IS NULL OR char_end >= char_start)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_passage ON mentions(passage_id);

CREATE TABLE IF NOT EXISTS relationship_types (
    type_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    directed    INTEGER NOT NULL DEFAULT 1,
    is_default  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id     TEXT PRIMARY KEY,
    source_entity_id    TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_entity_id    TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    type_id             INTEGER NOT NULL REFERENCES relationship_types(type_id),
    description         TEXT,
    evidence_passage_id TEXT REFERENCES passages(passage_id) ON DELETE SET NULL,
    doc_id              TEXT REFERENCES documents(doc_id) ON DELETE SET NULL,
    note                TEXT,
    confidence          TEXT CHECK (confidence IN ('low','medium','high')
                                    OR confidence IS NULL),
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_entity_id);
"""


def utc_now() -> str:
    """Current UTC timestamp as a sortable ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_connection(db_path: str | Path | None = None):
    """Open a connection with foreign keys enabled, commit or roll back."""
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
    conn.executemany(
        "INSERT INTO entity_categories (name, description, is_default) "
        "VALUES (?, ?, 1)",
        DEFAULT_CATEGORIES,
    )
    conn.executemany(
        "INSERT INTO relationship_types (name, description, directed, is_default) "
        "VALUES (?, ?, ?, 1)",
        DEFAULT_RELATIONSHIP_TYPES,
    )


def init_db(db_path: str | Path | None = None) -> None:
    """Create the schema if needed. Safe to call on every application start."""
    with get_connection(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(_SCHEMA_SQL)
            _seed_defaults(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is not supported by this "
                f"version of TextEncode (expected {SCHEMA_VERSION})."
            )


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _next_sequential_id(conn, table, column, prefix, width) -> str:
    """Return the next zero-padded ID, e.g. DOC-001 or ENT-000001."""
    row = conn.execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ? "
        f"ORDER BY {column} DESC LIMIT 1",
        (f"{prefix}-%",),
    ).fetchone()
    if row is None:
        number = 1
    else:
        number = int(row[0].split("-")[1]) + 1
    return f"{prefix}-{number:0{width}d}"


def next_doc_id(conn) -> str:
    return _next_sequential_id(conn, "documents", "doc_id", "DOC", 3)


def next_entity_id(conn) -> str:
    return _next_sequential_id(conn, "entities", "entity_id", "ENT", 6)


def next_mention_id(conn) -> str:
    return _next_sequential_id(conn, "mentions", "mention_id", "MEN", 6)


def next_relationship_id(conn) -> str:
    return _next_sequential_id(conn, "relationships", "relationship_id", "REL", 6)


# ---------------------------------------------------------------------------
# Documents and passages
# ---------------------------------------------------------------------------

_DOCUMENT_COLUMNS = (
    "doc_id, title, original_filename, file_hash, language, author, "
    "publication_info, import_date"
)


def save_document(conn, *, title: str, original_filename: str, source_text: str,
                  passages: list[dict], language: str | None = None,
                  author: str | None = None,
                  publication_info: str | None = None) -> str:
    """Insert one document and its passages in a single transaction.

    Raises DuplicateDocumentError if the exact same bytes were imported
    before (same SHA-256). A *changed* file is deliberately treated as a new
    document: annotations must never silently move to different text.
    """
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    existing = conn.execute(
        "SELECT doc_id FROM documents WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if existing is not None:
        raise DuplicateDocumentError(existing["doc_id"])

    doc_id = next_doc_id(conn)
    conn.execute(
        "INSERT INTO documents (doc_id, title, original_filename, file_hash, "
        "language, author, publication_info, source_text, import_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, title, original_filename, file_hash, language, author,
         publication_info, source_text, utc_now()),
    )

    rows = []
    for sequence, passage in enumerate(passages, start=1):
        rows.append((
            f"{doc_id}-P{sequence:03d}",
            doc_id,
            passage["passage_type"],
            sequence,
            passage.get("heading_level"),
            passage.get("heading_path") or "",
            passage["text"],
            passage["plain_text"],
            passage["char_start"],
            passage["char_end"],
            passage["content_hash"],
        ))
    conn.executemany(
        "INSERT INTO passages (passage_id, doc_id, passage_type, sequence, "
        "heading_level, heading_path, text, plain_text, char_start, char_end, "
        "content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return doc_id


def list_documents(conn) -> list[sqlite3.Row]:
    """All documents with a passage count, light-weight (no source_text)."""
    return conn.execute(
        f"SELECT {_DOCUMENT_COLUMNS}, "
        "(SELECT COUNT(*) FROM passages p WHERE p.doc_id = d.doc_id) "
        "AS passage_count "
        "FROM documents d ORDER BY d.doc_id"
    ).fetchall()


def get_document(conn, doc_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()


def get_passages(conn, doc_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT passage_id, doc_id, passage_type, sequence, heading_level, "
        "heading_path, text, plain_text, char_start, char_end, content_hash "
        "FROM passages WHERE doc_id = ? ORDER BY sequence",
        (doc_id,),
    ).fetchall()


def get_all_passages(conn) -> list[sqlite3.Row]:
    """All passages across all documents, ordered by document then sequence."""
    return conn.execute(
        "SELECT passage_id, doc_id, passage_type, sequence, heading_level, "
        "heading_path, text, plain_text, char_start, char_end, content_hash "
        "FROM passages ORDER BY doc_id, sequence"
    ).fetchall()


def delete_document(conn, doc_id: str) -> None:
    """Delete a document; passages (and later mentions) cascade."""
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


def database_stats(conn) -> dict:
    """Row counts for the dashboard. Table names are internal constants."""
    tables = {
        "documents": "documents",
        "passages": "passages",
        "entities": "entities",
        "mentions": "mentions",
        "relationships": "relationships",
        "categories": "entity_categories",
    }
    return {
        key: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for key, table in tables.items()
    }


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def get_categories(conn) -> list[sqlite3.Row]:
    """Return all entity categories."""
    return conn.execute(
        "SELECT category_id, name, description FROM entity_categories ORDER BY category_id"
    ).fetchall()


def save_entity(conn, *, canonical_name: str, category_id: int,
                alt_names: str | None = None, transliteration: str | None = None,
                description: str | None = None, notes: str | None = None,
                doc_id: str | None = None) -> str:
    """Insert a new entity and return its new ENT- ID."""
    entity_id = next_entity_id(conn)
    conn.execute(
        "INSERT INTO entities (entity_id, canonical_name, category_id, alt_names, "
        "transliteration, description, notes, doc_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entity_id, canonical_name, category_id, alt_names, transliteration,
         description, notes, doc_id, utc_now())
    )
    return entity_id


def get_entities(conn) -> list[sqlite3.Row]:
    """Return all entities joined with their category name."""
    return conn.execute(
        "SELECT e.entity_id, e.canonical_name, c.name as category, "
        "e.alt_names, e.transliteration, e.description, e.notes, e.doc_id, e.created_at "
        "FROM entities e "
        "JOIN entity_categories c ON e.category_id = c.category_id "
        "ORDER BY e.entity_id"
    ).fetchall()


def update_entity(conn, entity_id: str, *, canonical_name: str, category_id: int,
                  alt_names: str | None, transliteration: str | None,
                  description: str | None, notes: str | None) -> None:
    """Update an existing entity's details. The entity_id never changes."""
    conn.execute(
        "UPDATE entities SET canonical_name = ?, category_id = ?, alt_names = ?, "
        "transliteration = ?, description = ?, notes = ? WHERE entity_id = ?",
        (canonical_name, category_id, alt_names, transliteration,
         description, notes, entity_id)
    )


def delete_entity(conn, entity_id: str) -> None:
    """Delete an entity. Mentions cascade."""
    conn.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------

def save_mention(conn, *, entity_id: str, doc_id: str, passage_id: str,
                 surface_form: str, note: str | None = None,
                 status: str = 'verified') -> str:
    """Record a new occurrence of an entity in a specific passage."""
    mention_id = next_mention_id(conn)
    # We leave char_start and char_end as NULL for passage-level mentions
    conn.execute(
        "INSERT INTO mentions (mention_id, entity_id, doc_id, passage_id, "
        "surface_form, status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (mention_id, entity_id, doc_id, passage_id, surface_form, status, note, utc_now())
    )
    return mention_id


def get_mentions(conn) -> list[sqlite3.Row]:
    """Return all mentions joined with their entity and passage details."""
    return conn.execute(
        "SELECT m.mention_id, m.surface_form, m.status, m.note, m.created_at, "
        "e.entity_id, e.canonical_name, c.name as category, "
        "p.passage_id, p.plain_text, p.doc_id "
        "FROM mentions m "
        "JOIN entities e ON m.entity_id = e.entity_id "
        "JOIN entity_categories c ON e.category_id = c.category_id "
        "JOIN passages p ON m.passage_id = p.passage_id "
        "ORDER BY m.mention_id DESC"
    ).fetchall()


def delete_mention(conn, mention_id: str) -> None:
    """Delete a mention. The underlying entity and passage remain intact."""
    conn.execute("DELETE FROM mentions WHERE mention_id = ?", (mention_id,))


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

def get_relationship_types(conn) -> list[sqlite3.Row]:
    """Return all relationship types."""
    return conn.execute(
        "SELECT type_id, name, description, directed FROM relationship_types ORDER BY type_id"
    ).fetchall()


def save_relationship(conn, *, source_entity_id: str, target_entity_id: str,
                      type_id: int, description: str | None = None,
                      evidence_passage_id: str | None = None,
                      doc_id: str | None = None, note: str | None = None,
                      confidence: str | None = None) -> str:
    """Record a new relationship between two entities."""
    relationship_id = next_relationship_id(conn)
    conn.execute(
        "INSERT INTO relationships (relationship_id, source_entity_id, target_entity_id, "
        "type_id, description, evidence_passage_id, doc_id, note, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (relationship_id, source_entity_id, target_entity_id, type_id,
         description, evidence_passage_id, doc_id, note, confidence, utc_now())
    )
    return relationship_id


def get_relationships(conn) -> list[sqlite3.Row]:
    """Return all relationships joined with entity names and passage details."""
    return conn.execute(
        "SELECT r.relationship_id, r.source_entity_id, s.canonical_name as source_name, "
        "r.target_entity_id, t.canonical_name as target_name, "
        "rt.name as relationship_type, r.description, r.confidence, "
        "r.evidence_passage_id, p.plain_text as evidence_text "
        "FROM relationships r "
        "JOIN entities s ON r.source_entity_id = s.entity_id "
        "JOIN entities t ON r.target_entity_id = t.entity_id "
        "JOIN relationship_types rt ON r.type_id = rt.type_id "
        "LEFT JOIN passages p ON r.evidence_passage_id = p.passage_id "
        "ORDER BY r.relationship_id DESC"
    ).fetchall()


def delete_relationship(conn, relationship_id: str) -> None:
    """Delete a relationship. The underlying entities remain intact."""
    conn.execute("DELETE FROM relationships WHERE relationship_id = ?", (relationship_id,))