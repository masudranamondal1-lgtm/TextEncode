import os, shutil, sys, re
from pathlib import Path

ROOT = Path.cwd()
def backup(p):
    src = ROOT / p
    if src.is_file():
        shutil.copy2(src, src.with_suffix(src.suffix + ".pre_phase5.bak"))
        print(f"  backup: {src.name}.pre_phase5.bak")

def write(p, text):
    fp = ROOT / p
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(text, encoding="utf-8")
    print(f"  wrote: {p}")

print("== Phase 5 bootstrap: targeted fixes ==")

# ---------- 1. database/db.py ----------
print("\n[1/4] database/db.py")
backup("database/db.py")
db = (ROOT / "database/db.py").read_text(encoding="utf-8")

# Fix the corrupted dunder names
db = db.replace("from future import annotations", "from __future__ import annotations")
db = db.replace("Path(file).resolve()", "Path(__file__).resolve()")
db = db.replace("def init(self, existing_doc_id", "def __init__(self, existing_doc_id")
db = db.replace("def init(self, message", "def __init__(self, message")
db = db.replace("super().init(", "super().__init__(")
db = db.replace("SCHEMA_VERSION = 5", "SCHEMA_VERSION = 6")

# Add new tables into init_db's executescript (right before the closing triple-quote of the schema)
marker = 'CREATE TABLE IF NOT EXISTS audit_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT, record_type TEXT NOT NULL, record_id TEXT NOT NULL, operation TEXT NOT NULL, old_value TEXT, new_value TEXT, timestamp TEXT NOT NULL, origin TEXT NOT NULL);'
new_tables = marker + """
            CREATE TABLE IF NOT EXISTS external_authorities (authority_id INTEGER PRIMARY KEY AUTOINCREMENT, provider_name TEXT NOT NULL UNIQUE, namespace TEXT NOT NULL, base_uri TEXT, enabled INTEGER DEFAULT 1, attribution TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entity_identifiers (identifier_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, authority_id INTEGER NOT NULL REFERENCES external_authorities(authority_id), external_identifier TEXT NOT NULL, external_uri TEXT, external_label TEXT, match_status TEXT DEFAULT 'accepted', researcher_note TEXT, accepted_at TEXT, UNIQUE(entity_id, authority_id, external_identifier));
            CREATE TABLE IF NOT EXISTS reconciliation_candidates (candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE, authority_id INTEGER NOT NULL REFERENCES external_authorities(authority_id), external_identifier TEXT NOT NULL, external_uri TEXT, external_label TEXT, external_description TEXT, alternative_names TEXT, search_query TEXT, review_status TEXT DEFAULT 'suggested', created_at TEXT NOT NULL);"""
if marker in db and "external_authorities" not in db:
    db = db.replace(marker, new_tables)

# Add the add_col migrations for Phase 3/4/5 columns
anchor = 'add_col("mentions", "deleted_at", "TEXT DEFAULT NULL")'
extra_cols = anchor + """
        add_col("evidence_bundles", "source_type", "TEXT")
        add_col("evidence_bundles", "source_identifier", "TEXT")
        add_col("evidence_bundles", "author", "TEXT")
        add_col("evidence_bundles", "source_title", "TEXT")
        add_col("evidence_bundles", "publisher", "TEXT")
        add_col("evidence_bundles", "publication_year", "TEXT")
        add_col("evidence_bundles", "page_reference", "TEXT")
        add_col("evidence_bundles", "url", "TEXT")
        add_col("evidence_bundles", "access_date", "TEXT")
        add_col("evidence_bundles", "verification_status", "TEXT DEFAULT 'unverified'")
        add_col("evidence_bundles", "researcher_note", "TEXT")
        add_col("evidence_bundles", "deleted_at", "TEXT DEFAULT NULL")
        add_col("relationships", "research_assessment", "TEXT DEFAULT 'unassessed'")
        add_col("entities", "geometry_json", "TEXT")
        add_col("entities", "coordinate_source", "TEXT DEFAULT 'researcher'")
        add_col("projects", "deleted_at", "TEXT DEFAULT NULL")
        add_col("projects", "updated_at", "TEXT")
        add_col("corpora", "deleted_at", "TEXT DEFAULT NULL")
        add_col("taxonomy_profiles", "deleted_at", "TEXT DEFAULT NULL")"""
if anchor in db and "geometry_json" not in db:
    db = db.replace(anchor, extra_cols)

# Append all missing Phase 3/4/5 functions (idempotent: only if not present)
if "def init_external_authorities" not in db:
    db += """

# =====================================================================
# PHASE 3/4/5 — Audit, projects, corpora, profiles, geometry, scope,
# relationship assessment, structured evidence, linked data, provenance
# =====================================================================
def log_audit(conn, record_type, record_id, operation, old_value=None, new_value=None, origin="ui"):
    conn.execute(
        "INSERT INTO audit_log (record_type, record_id, operation, old_value, new_value, timestamp, origin) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (record_type, record_id, operation, old_value, new_value, utc_now(), origin))

def list_projects(conn, include_deleted=False):
    q = "SELECT * FROM projects" + ("" if include_deleted else " WHERE deleted_at IS NULL") + " ORDER BY project_id"
    return conn.execute(q).fetchall()
def update_project(conn, project_id, name, description):
    if not name.strip(): raise ValueError("Project name cannot be empty.")
    conn.execute("UPDATE projects SET name=?, description=?, updated_at=? WHERE project_id=?",
                 (name.strip(), description.strip() or None, utc_now(), project_id))
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
    log_audit(conn, "projects", str(project_id), "hard_deleted")

def update_corpus(conn, corpus_id, name, description):
    if not name.strip(): raise ValueError("Corpus name cannot be empty.")
    conn.execute("UPDATE corpora SET name=?, description=? WHERE corpus_id=?", (name.strip(), description.strip() or None, corpus_id))
def soft_delete_corpus(conn, corpus_id):
    conn.execute("UPDATE corpora SET deleted_at=? WHERE corpus_id=?", (utc_now(), corpus_id))
def restore_corpus(conn, corpus_id):
    conn.execute("UPDATE corpora SET deleted_at=NULL WHERE corpus_id=?", (corpus_id,))
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
    conn.execute("UPDATE taxonomy_profiles SET name=?, description=?, is_active=? WHERE profile_id=?",
                 (name.strip(), description.strip() or None, int(is_active), profile_id))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "updated", new_value=name.strip())
def soft_delete_profile(conn, profile_id):
    conn.execute("UPDATE taxonomy_profiles SET deleted_at=?, is_active=0 WHERE profile_id=?", (utc_now(), profile_id))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "soft_deleted")
def restore_profile(conn, profile_id):
    conn.execute("UPDATE taxonomy_profiles SET deleted_at=NULL WHERE profile_id=?", (profile_id,))
def hard_delete_profile(conn, profile_id):
    if conn.execute("SELECT COUNT(*) FROM entities WHERE profile_id=?", (profile_id,)).fetchone()[0] > 0:
        raise ValueError("Cannot permanently delete a profile that still has entities.")
    conn.execute("DELETE FROM entity_categories WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM relationship_types WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM attribute_definitions WHERE profile_id=?", (profile_id,))
    conn.execute("DELETE FROM taxonomy_profiles WHERE profile_id=?", (profile_id,))
    log_audit(conn, "taxonomy_profiles", str(profile_id), "hard_deleted")

def set_entity_geometry(conn, entity_id, geometry_type, geometry_json, latitude, longitude):
    conn.execute("UPDATE entities SET geometry_type=?, geometry_json=?, latitude=?, longitude=? WHERE entity_id=?",
                 (geometry_type, geometry_json, latitude, longitude, entity_id))
    log_audit(conn, "entities", entity_id, "geometry_updated", new_value=geometry_type)

def list_relationships(conn, *, scope="doc", doc_id=None):
    base = \"\"\"
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
    \"\"\"
    params = []
    if scope == "doc" and doc_id:
        base += " AND r.doc_id = ?"; params.append(doc_id)
    elif scope == "unassigned":
        base += " AND r.doc_id IS NULL"
    base += " ORDER BY r.created_at DESC"
    return conn.execute(base, params).fetchall()

def save_relationship(conn, source_id, target_id, type_id, description, doc_id=None, confidence=None, research_assessment="unassessed"):
    rel_id = next_relationship_id(conn)
    if confidence not in {"low", "medium", "high", None}: confidence = None
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

def get_evidence_for_relationship(conn, rel_id):
    return conn.execute("SELECT * FROM evidence_bundles WHERE relationship_id=? AND deleted_at IS NULL ORDER BY evidence_id", (rel_id,)).fetchall()
def add_evidence_bundle(conn, rel_id, domain, source_text, context="", *, source_type=None, source_identifier=None, author=None, source_title=None, publisher=None, publication_year=None, page_reference=None, url=None, access_date=None, verification_status="unverified", researcher_note=None):
    if not source_text or not source_text.strip(): raise ValueError("Evidence source text cannot be empty.")
    if verification_status not in {"unverified","checked","corroborated","contested","rejected"}: raise ValueError(f"Invalid verification status: {verification_status}")
    conn.execute("INSERT INTO evidence_bundles (relationship_id, evidence_domain, source_text, context, created_at, source_type, source_identifier, author, source_title, publisher, publication_year, page_reference, url, access_date, verification_status, researcher_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (rel_id, domain, source_text.strip(), context, utc_now(), source_type, source_identifier, author, source_title, publisher, publication_year, page_reference, url, access_date, verification_status, researcher_note))
    ev_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_audit(conn, "evidence_bundles", str(ev_id), "created", new_value=f"rel={rel_id}")
    return ev_id
def update_evidence_bundle(conn, evidence_id, **kwargs):
    allowed = {"evidence_domain","source_text","context","source_type","source_identifier","author","source_title","publisher","publication_year","page_reference","url","access_date","verification_status","researcher_note"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates: return
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE evidence_bundles SET {sets} WHERE evidence_id=? AND deleted_at IS NULL", list(updates.values()) + [evidence_id])
    log_audit(conn, "evidence_bundles", str(evidence_id), "updated", new_value=str(updates))
def soft_delete_evidence(conn, evidence_id):
    conn.execute("UPDATE evidence_bundles SET deleted_at=? WHERE evidence_id=? AND deleted_at IS NULL", (utc_now(), evidence_id))
    log_audit(conn, "evidence_bundles", str(evidence_id), "soft_deleted")

def init_external_authorities(conn):
    if conn.execute("SELECT COUNT(*) FROM external_authorities").fetchone()[0] == 0:
        now = utc_now()
        conn.execute("INSERT INTO external_authorities (provider_name, namespace, base_uri, enabled, attribution, created_at) VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)",
                     ("Wikidata","wikidata","http://www.wikidata.org/entity/",1,"Wikidata is a free and open knowledge base.",now,
                      "GeoNames","geonames","http://sws.geonames.org/",1,"GeoNames is a geographical database.",now))
def get_enabled_authorities(conn):
    return conn.execute("SELECT * FROM external_authorities WHERE enabled = 1").fetchall()
def add_entity_identifier(conn, entity_id, authority_id, external_identifier, external_uri, external_label, match_status="accepted", researcher_note=""):
    existing = conn.execute("SELECT identifier_id FROM entity_identifiers WHERE entity_id=? AND authority_id=? AND external_identifier=?", (entity_id, authority_id, external_identifier)).fetchone()
    if existing: return existing["identifier_id"]
    conn.execute("INSERT INTO entity_identifiers (entity_id, authority_id, external_identifier, external_uri, external_label, match_status, researcher_note, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (entity_id, authority_id, external_identifier, external_uri, external_label, match_status, researcher_note, utc_now()))
    log_audit(conn, "entity_identifiers", str(conn.execute("SELECT last_insert_rowid()").fetchone()[0]), "created", new_value=f"{entity_id}->{external_identifier}")
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
def remove_entity_identifier(conn, identifier_id):
    conn.execute("DELETE FROM entity_identifiers WHERE identifier_id = ?", (identifier_id,))
def get_external_identifiers(conn, entity_id):
    return conn.execute("SELECT ei.*, ea.provider_name, ea.namespace FROM entity_identifiers ei JOIN external_authorities ea ON ei.authority_id = ea.authority_id WHERE ei.entity_id = ?", (entity_id,)).fetchall()
def save_reconciliation_candidates(conn, entity_id, authority_id, candidates, search_query):
    count = 0
    for c in candidates:
        existing = conn.execute("SELECT candidate_id FROM reconciliation_candidates WHERE entity_id=? AND external_identifier=? AND review_status='suggested'", (entity_id, c["external_identifier"])).fetchone()
        if not existing:
            conn.execute("INSERT INTO reconciliation_candidates (entity_id, authority_id, external_identifier, external_uri, external_label, external_description, alternative_names, search_query, review_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?)",
                         (entity_id, authority_id, c["external_identifier"], c["external_uri"], c["external_label"], c.get("external_description",""), c.get("alternative_names",""), search_query, utc_now()))
            count += 1
    return count
def get_candidates_for_entity(conn, entity_id, review_status="suggested"):
    return conn.execute("SELECT rc.*, ea.provider_name FROM reconciliation_candidates rc JOIN external_authorities ea ON rc.authority_id = ea.authority_id WHERE rc.entity_id = ? AND rc.review_status = ? ORDER BY rc.created_at DESC", (entity_id, review_status)).fetchall()
def update_reconciliation_candidate_status(conn, candidate_id, status):
    allowed = {"accepted","rejected","deferred","superseded"}
    if status not in allowed: raise ValueError(f"Invalid status: {status}")
    conn.execute("UPDATE reconciliation_candidates SET review_status = ? WHERE candidate_id = ?", (status, candidate_id))
"""

write("database/db.py", db)

# ---------- 2. modules/bengali_nlp.py ----------
print("\n[2/4] modules/bengali_nlp.py")
backup("modules/bengali_nlp.py")
bnlp = (ROOT / "modules/bengali_nlp.py").read_text(encoding="utf-8")
bnlp = bnlp.replace("def init(self):", "def __init__(self):")
if "def extract_candidates" not in bnlp:
    bnlp += """

def extract_candidates(passages, cat_map, existing_entities, progress_callback=None):
    \"\"\"Scan passages with BengaliAnalyzer and return candidate dicts.\"\"\"
    from datetime import datetime, timezone
    analyzer = BengaliAnalyzer()
    candidates = []
    known = {}
    for ent in existing_entities:
        known[ent["canonical_name"].lower()] = ent["category_id"]
        if ent.get("alt_names"):
            for alias in ent["alt_names"].split(","):
                known[alias.strip().lower()] = ent["category_id"]
    total = len(passages)
    for idx, passage in enumerate(passages):
        if progress_callback:
            progress_callback(idx + 1, total)
        text = passage["plain_text"]
        if not text:
            continue
        for token_data in analyzer.process_text(text):
            if token_data["type"] != "noun":
                continue
            surface, root = token_data["surface"], token_data["root"]
            suggested_cat_id = None
            method = "Bengali Noun Root Extraction"
            confidence = 0.4
            reason = f"Identified as a base noun/root ('{root}'). No exact entity match found."
            if root.lower() in known:
                suggested_cat_id = known[root.lower()]
                method = "Known Entity Alias/Root Match"
                confidence = 0.85
                reason = f"Root '{root}' exactly matches an existing entity alias or canonical name."
            else:
                suggested_cat_id = cat_map.get("other") or cat_map.get("person")
            if suggested_cat_id is None:
                continue
            candidates.append({
                "doc_id": passage["doc_id"],
                "passage_id": passage["passage_id"],
                "surface_form": surface,
                "char_start": token_data["start"],
                "char_end": token_data["end"],
                "suggested_category_id": suggested_cat_id,
                "confidence_score": confidence,
                "recognition_method": method,
                "recognition_reason": reason,
                "contextual_evidence": f"Features: {token_data.get('features', [])}",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
    return candidates
"""
write("modules/bengali_nlp.py", bnlp)

# ---------- 3. modules/exporter.py ----------
print("\n[3/4] modules/exporter.py")
backup("modules/exporter.py")
exp = (ROOT / "modules/exporter.py").read_text(encoding="utf-8")
exp = exp.replace("from future import annotations", "from __future__ import annotations")
exp = exp.replace('tables = { "documents ":  "SELECT * FROM documents WHERE deleted_at IS NULL ",  "passages ":  "SELECT * FROM passages ",  "entities ":  "SELECT * FROM entities WHERE deleted_at IS NULL ",  "mentions ":  "SELECT mentions WHERE deleted_at IS NULL ",  "relationships ":  "SELECT relationships WHERE deleted_at IS NULL ",  "evidence_bundles ":  "SELECT evidence_bundles "}',
                  'tables = {"documents": "SELECT * FROM documents WHERE deleted_at IS NULL", "passages": "SELECT * FROM passages", "entities": "SELECT * FROM entities WHERE deleted_at IS NULL", "mentions": "SELECT * FROM mentions WHERE deleted_at IS NULL", "relationships": "SELECT * FROM relationships WHERE deleted_at IS NULL", "evidence_bundles": "SELECT * FROM evidence_bundles WHERE deleted_at IS NULL"}')
# Replace generate_json_export to include external identifiers
exp = re.sub(r"def generate_json_export\(conn\).*?return json\.dumps\(data, ensure_ascii=False, indent=2\)",
'''def generate_json_export(conn) -> str:
    tables = {"documents": "SELECT * FROM documents WHERE deleted_at IS NULL", "passages": "SELECT * FROM passages", "entities": "SELECT * FROM entities WHERE deleted_at IS NULL", "mentions": "SELECT * FROM mentions WHERE deleted_at IS NULL", "relationships": "SELECT * FROM relationships WHERE deleted_at IS NULL", "evidence_bundles": "SELECT * FROM evidence_bundles WHERE deleted_at IS NULL"}
    data = {}
    for name, query in tables.items():
        data[name] = [dict(row) for row in conn.execute(query).fetchall()]
    has_ext = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='external_authorities'").fetchone()
    if has_ext:
        data["external_authorities"] = [dict(r) for r in conn.execute("SELECT * FROM external_authorities").fetchall()]
        data["entity_identifiers"] = [dict(r) for r in conn.execute("SELECT ei.*, ea.provider_name FROM entity_identifiers ei JOIN external_authorities ea ON ei.authority_id = ea.authority_id").fetchall()]
    return json.dumps(data, ensure_ascii=False, indent=2)''', exp, flags=re.DOTALL)
# Replace generate_qgis_geojson to include external URIs + provenance
exp = re.sub(r"def generate_qgis_geojson\(conn\).*?return json\.dumps\(\{ ?type ?:.+?\}, ensure_ascii=False, indent=2\)",
'''def generate_qgis_geojson(conn) -> str:
    has_ext = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_identifiers'").fetchone()
    has_geom = conn.execute("SELECT 1 FROM pragma_table_info('entities') WHERE name='geometry_json'").fetchone()
    cols = "e.entity_id, e.canonical_name, e.latitude, e.longitude, e.category_id, e.geometry_type, e.coordinate_source"
    if has_geom: cols += ", e.geometry_json"
    join = " LEFT JOIN entity_identifiers ei ON e.entity_id = ei.entity_id" if has_ext else ""
    grp = " GROUP BY e.entity_id" if has_ext else ""
    ext_sel = ", GROUP_CONCAT(DISTINCT ei.external_uri) AS external_uris" if has_ext else ""
    sql = f"SELECT {cols}{ext_sel} FROM entities e{join} WHERE e.deleted_at IS NULL AND (e.latitude IS NOT NULL OR (e.geometry_json IS NOT NULL AND e.geometry_json <> '')){grp}"
    features = []
    for r in conn.execute(sql).fetchall():
        d = dict(r)
        geometry = None
        provenance = d.get("coordinate_source") or "researcher"
        if has_geom and d.get("geometry_json"):
            try:
                geometry = json.loads(d["geometry_json"])
                provenance = f"{provenance} ({d.get('geometry_type') or geometry.get('type')})"
            except Exception:
                geometry = None
        if geometry is None and d["latitude"] is not None and d["longitude"] is not None:
            geometry = {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]}
        if geometry is None:
            continue
        features.append({"type": "Feature", "geometry": geometry, "properties": {
            "entity_id": d["entity_id"], "name": d["canonical_name"], "category_id": d["category_id"],
            "coordinate_source": provenance, "external_uris": d.get("external_uris") or ""}})
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)''', exp, flags=re.DOTALL)
write("modules/exporter.py", exp)

# ---------- 4. app.py ----------
print("\n[4/4] app.py")
backup("app.py")
app = (ROOT / "app.py").read_text(encoding="utf-8")
app = app.replace("from future import annotations", "from __future__ import annotations")
app = app.replace("Path(file).resolve()", "Path(__file__).resolve()")

# Remove the entire v0.6.1 override section that redefines pages and breaks Phase 4/5
override_marker = "v0.6.1 COMPATIBILITY AND SCOPED ANALYSIS OVERRIDES"
nav_marker = "NAVIGATION"
if override_marker in app and nav_marker in app:
    start = app.index(override_marker)
    # find the comment block start (the dashes before it)
    block_start = app.rfind("---------------------------------------------------------------------", 0, start)
    end = app.index(nav_marker, start)
    block_end = app.rfind("---------------------------------------------------------------------", start, end)
    app = app[:block_start] + app[block_end:]

# Replace page_entities with the 5-tab version including External Identity
pe_start = app.index("def page_entities()")
pe_end = app.index("def page_relationships()", pe_start) if "def page_relationships()" in app[pe_start:] else app.index("---------------------------------------------------------------------", pe_start)
new_pe = '''def page_entities() -> None:
    components.page_header("Entity Catalogue",
        "Manage canonical entities, inspect document-specific mentions, and reconcile with external authorities.")
    with db.get_connection() as conn:
        profiles = db.list_profiles(conn)
        documents = db.list_documents(conn)
    if not profiles:
        render_empty("Create a taxonomy profile before registering entities.")
        return
    profile = get_active_profile(conn)
    profile_id = profile["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        entities = db.get_all_entities_with_stats(conn, profile_id)
    if not categories:
        render_empty("The selected taxonomy profile has no categories.")
        return
    category_options = {c["name"]: c["category_id"] for c in categories}
    view_tab, add_tab, edit_tab, document_tab, external_tab = st.tabs(
        ["Catalogue", "Add Seed Entity", "Edit Entity", "By Document", "External Identity"])
    with view_tab:
        if not entities:
            st.info("No entities have been registered.")
        else:
            frame = pd.DataFrame(rows_as_dicts(entities))
            try:
                with db.get_connection() as conn:
                    has_ids = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_identifiers'").fetchone()
                    ext_rows = conn.execute("SELECT entity_id, COUNT(*) AS ext_count, GROUP_CONCAT(external_identifier) AS ext_ids FROM entity_identifiers GROUP BY entity_id").fetchall() if has_ids else []
                counts = {r["entity_id"]: (r["ext_count"], r["ext_ids"]) for r in ext_rows}
                frame["external_links"] = frame["entity_id"].map(lambda eid: counts.get(eid, (0, ""))[0])
                frame["external_ids"] = frame["entity_id"].map(lambda eid: counts.get(eid, (0, ""))[1])
            except Exception:
                frame["external_links"] = 0
                frame["external_ids"] = ""
            col_search, col_category = st.columns([2, 1])
            search = col_search.text_input("Search entity name or alias", key="entity_search")
            category_filter = col_category.selectbox("Category", ["All"] + list(category_options.keys()), key="entity_category_filter")
            if search:
                pattern = search.strip()
                frame = frame[frame["canonical_name"].fillna("").str.contains(pattern, case=False, regex=False) | frame["alt_names"].fillna("").str.contains(pattern, case=False, regex=False)]
            if category_filter != "All":
                frame = frame[frame["category_name"] == category_filter]
            visible_columns = [c for c in ["entity_id", "canonical_name", "alt_names", "category_name", "mention_count", "external_links", "external_ids"] if c in frame.columns]
            st.dataframe(frame[visible_columns], hide_index=True, width="stretch")
    with add_tab:
        with st.form("add_seed_entity_form"):
            canonical_name = st.text_input("Canonical name *")
            category_name = st.selectbox("Category", list(category_options.keys()))
            aliases = st.text_input("Alternative names", help="Separate aliases with commas.")
            description = st.text_area("Description")
            submitted = st.form_submit_button("Register Entity", type="primary")
        if submitted:
            if not canonical_name.strip():
                st.error("Canonical name is required.")
            else:
                with db.get_connection() as conn:
                    entity_id = db.next_entity_id(conn)
                    conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, alt_names, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (entity_id, profile_id, canonical_name.strip(), category_options[category_name], aliases.strip() or None, description.strip() or None, db.utc_now()))
                safe_rerun()
    with edit_tab:
        if not entities:
            st.info("There are no entities to edit.")
        else:
            entity_map = {f"{e['entity_id']} — {e['canonical_name']}": dict(e) for e in entities}
            selected = st.selectbox("Select entity", list(entity_map.keys()), key="edit_entity_selection")
            entity = entity_map[selected]
            with st.form("edit_entity_details_form"):
                new_name = st.text_input("Canonical name", value=entity["canonical_name"] or "")
                category_names = list(category_options.keys())
                current_category = entity["category_name"]
                category_index = category_names.index(current_category) if current_category in category_names else 0
                new_category = st.selectbox("Category", category_names, index=category_index)
                new_aliases = st.text_input("Alternative names", value=entity["alt_names"] or "")
                new_description = st.text_area("Description", value=entity["description"] or "")
                save = st.form_submit_button("Save Entity Changes", type="primary")
            if save:
                if not new_name.strip():
                    st.error("Canonical name cannot be empty.")
                else:
                    with db.get_connection() as conn:
                        db.update_entity_details(conn, entity["entity_id"], new_name.strip(), category_options[new_category], new_aliases.strip() or None, new_description.strip() or None)
                    safe_rerun()
            st.warning("Moving an entity to Trash hides it from active catalogues. Existing mentions remain stored.")
            if st.button("Move Entity to Trash", key=f"trash_entity_{entity['entity_id']}"):
                with db.get_connection() as conn:
                    db.soft_delete_entity(conn, entity["entity_id"])
                safe_rerun()
            st.subheader("Mentions of this entity")
            with db.get_connection() as conn:
                mentions = db.get_mentions_for_entity(conn, entity["entity_id"])
            if mentions:
                for mention in mentions:
                    with st.container(border=True):
                        st.markdown(f"**{mention['mention_id']}** · `{mention['surface_form']}`")
                        st.caption(f"Passage: {mention['passage_id']}")
                        st.write(mention["plain_text"])
                        if st.button("Move mention to Trash", key=f"trash_mention_{mention['mention_id']}"):
                            with db.get_connection() as conn:
                                db.delete_mention(conn, mention["mention_id"])
                            safe_rerun()
            else:
                st.info("No active mentions are linked to this entity.")
    with document_tab:
        if not documents:
            st.info("Import documents to inspect document-specific entities.")
        else:
            doc_options = make_document_options(documents)
            selected_doc = st.selectbox("Document", list(doc_options.keys()), key="entity_document_scope")
            doc_id = doc_options[selected_doc]
            with db.get_connection() as conn:
                document_entities = scoped_entity_rows(conn, profile_id, doc_id)
                mention_rows = conn.execute("SELECT m.mention_id, m.entity_id, e.canonical_name, m.surface_form, m.passage_id, m.char_start, m.char_end, m.status, m.note FROM mentions m JOIN entities e ON e.entity_id = m.entity_id WHERE m.doc_id = ? AND m.deleted_at IS NULL ORDER BY m.passage_id, m.char_start", (doc_id,)).fetchall()
            st.subheader("Entities mentioned in this document")
            present = [dict(row) for row in document_entities if row["mention_count"] > 0]
            if present:
                st.dataframe(pd.DataFrame(present), hide_index=True, width="stretch")
            else:
                st.info("No entity mentions have been annotated in this document.")
            st.subheader("Document mention register")
            if mention_rows:
                st.dataframe(pd.DataFrame(rows_as_dicts(mention_rows)), hide_index=True, width="stretch")
            else:
                st.info("No mentions are registered for this document.")
    with external_tab:
        st.subheader("External Authority Reconciliation")
        st.caption("Connect internal entities to external knowledge bases. Researcher authority is required for all matches.")
        if not entities:
            st.info("Register an entity first to begin reconciliation.")
            return
        entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
        selected_entity_label = st.selectbox("Select Entity to Reconcile", list(entity_options.keys()), key="reconcile_entity_select")
        entity_id = entity_options[selected_entity_label]
        with db.get_connection() as conn:
            db.init_external_authorities(conn)
            identifiers = [dict(i) for i in db.get_external_identifiers(conn, entity_id)]
            candidates = [dict(c) for c in db.get_candidates_for_entity(conn, entity_id, "suggested")]
            authorities = [dict(a) for a in db.get_enabled_authorities(conn)]
        st.markdown("### 1. Accepted Identifiers")
        if identifiers:
            for ident in identifiers:
                with st.container(border=True):
                    st.markdown(f"**{ident['provider_name']}**: [{ident['external_identifier']}]({ident['external_uri']})")
                    st.caption(f"Label: {ident['external_label']} | Status: {ident['match_status']}")
                    if st.button("Detach", key=f"detach_{ident['identifier_id']}"):
                        with db.get_connection() as conn:
                            db.remove_entity_identifier(conn, ident["identifier_id"])
                        safe_rerun()
        else:
            st.info("No external identifiers linked yet.")
        st.divider()
        st.markdown("### 2. Search External Authorities")
        if not authorities:
            st.warning("No authorities enabled in the database.")
        else:
            auth_options = {a["provider_name"]: a["authority_id"] for a in authorities}
            selected_auth_name = st.selectbox("Provider", list(auth_options.keys()), key="reconcile_auth_select")
            auth_id = auth_options[selected_auth_name]
            query = st.text_input("Search Query (use the entity's real name)", key="reconcile_query")
            lang = st.radio("Language", ["en", "bn"], horizontal=True, key="reconcile_lang")
            if st.button("Search", type="primary", key="reconcile_search_btn"):
                if not query.strip():
                    st.error("Enter a search query.")
                elif selected_auth_name != "Wikidata":
                    st.info("Only the Wikidata adapter is currently wired up. Select Wikidata.")
                else:
                    with st.spinner(f"Searching {selected_auth_name}..."):
                        try:
                            from modules.authorities.wikidata import WikidataProvider
                            results = WikidataProvider().search(query.strip(), language=lang)
                            if results:
                                with db.get_connection() as conn:
                                    db.save_reconciliation_candidates(conn, entity_id, auth_id, results, query.strip())
                                st.success(f"Found {len(results)} result(s).")
                                safe_rerun()
                            else:
                                st.info("No results found. Try an English proper name (e.g., 'Tagore', 'Kolkata').")
                        except ConnectionError as e:
                            st.error(str(e))
                        except Exception as e:
                            st.error(f"Search failed: {e}")
        st.divider()
        st.markdown("### 3. Review Candidates")
        if candidates:
            for c in candidates:
                with st.container(border=True):
                    st.markdown(f"**{c['external_label']}** ({c['provider_name']})")
                    st.markdown(f"🔗 [{c['external_uri']}]({c['external_uri']})")
                    if c.get("external_description"):
                        st.caption(c["external_description"])
                    if c.get("alternative_names"):
                        st.caption(f"Aliases: {c['alternative_names']}")
                    col1, col2, col3 = st.columns(3)
                    if col1.button("✅ Accept", key=f"acc_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.add_entity_identifier(conn, entity_id, c["authority_id"], c["external_identifier"], c["external_uri"], c["external_label"])
                            db.update_reconciliation_candidate_status(conn, c["candidate_id"], "accepted")
                        safe_rerun()
                    if col2.button("❌ Reject", key=f"rej_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.update_reconciliation_candidate_status(conn, c["candidate_id"], "rejected")
                        safe_rerun()
                    if col3.button("⏸️ Defer", key=f"def_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.update_reconciliation_candidate_status(conn, c["candidate_id"], "deferred")
                        safe_rerun()
        else:
            st.info("No pending candidates. Run a search above.")


'''
app = app[:pe_start] + new_pe + app[pe_end:]

# Ensure the authority module exists
os.makedirs(ROOT / "modules/authorities", exist_ok=True)
if not (ROOT / "modules/authorities/__init__.py").exists():
    write("modules/authorities/__init__.py", '"""External Authority Providers for TextEncode."""\n')
if not (ROOT / "modules/authorities/wikidata.py").exists():
    write("modules/authorities/wikidata.py", '''"""Wikidata API Adapter for TextEncode."""
import requests
from typing import List, Dict, Any

USER_AGENT = "TextEncode/0.6 (Digital Humanities research tool; https://github.com/masudranamondal1-lgtm/TextEncode)"

class WikidataProvider:
    name = "Wikidata"
    namespace = "wikidata"
    base_uri = "http://www.wikidata.org/entity/"
    def search(self, query: str, language: str = "en") -> List[Dict[str, Any]]:
        params = {"action": "wbsearchentities", "search": query, "language": language, "uselang": language, "format": "json", "limit": 10}
        try:
            resp = requests.get("https://www.wikidata.org/w/api.php", params=params, timeout=10, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Wikidata API unavailable: {e}")
        out = []
        for item in data.get("search", []):
            out.append({"external_identifier": item.get("id", ""), "external_uri": f"http://www.wikidata.org/entity/{item.get('id', '')}", "external_label": item.get("label", ""), "external_description": item.get("description", ""), "alternative_names": ", ".join(item.get("aliases", []) or []), "provider": self.name})
        return out
''')

write("app.py", app)

print("\n== Bootstrap complete. Verifying syntax... ==")
import py_compile
for f in ["database/db.py", "app.py", "modules/bengali_nlp.py", "modules/exporter.py", "modules/authorities/wikidata.py"]:
    try:
        py_compile.compile(str(ROOT / f), doraise=True)
        print(f"  OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"  FAIL: {f}\n{e}")
        sys.exit(1)
print("\nAll files compile. Run: python -m pytest -q")
