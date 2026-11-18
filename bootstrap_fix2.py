import shutil, py_compile, sys
from pathlib import Path

ROOT = Path.cwd()
def backup(p):
    src = ROOT / p
    if src.is_file():
        shutil.copy2(src, src.with_suffix(src.suffix + ".pre_fix2.bak"))
        print(f"  backup: {src.name}.pre_fix2.bak")

print("== Phase 5 fix-2: closed-conn + exporter contract ==")

# ---------- 1. app.py : surgical one-block replace ----------
print("\n[1/2] app.py (page_entities closed-conn)")
backup("app.py")
app = (ROOT / "app.py").read_text(encoding="utf-8")

broken = '''    with db.get_connection() as conn:
        profiles = db.list_profiles(conn)
        documents = db.list_documents(conn)
    if not profiles:
        render_empty("Create a taxonomy profile before registering entities.")
        return
    profile = get_active_profile(conn)
    profile_id = profile["profile_id"]'''

fixed = '''    with db.get_connection() as conn:
        profiles = db.list_profiles(conn)
        documents = db.list_documents(conn)
        profile = get_active_profile(conn)
    if not profiles or not profile:
        render_empty("Create a taxonomy profile before registering entities.")
        return
    profile_id = profile["profile_id"]'''

n = app.count(broken)
if n != 1:
    print(f"  ERROR: expected 1 match for broken block, found {n}. Aborting app.py edit.")
    sys.exit(1)
app = app.replace(broken, fixed)
(ROOT / "app.py").write_text(app, encoding="utf-8")
print("  patched page_entities")

# ---------- 2. modules/exporter.py : full rewrite to match tests ----------
print("\n[2/2] modules/exporter.py (test contract)")
backup("modules/exporter.py")
(ROOT / "modules/exporter.py").write_text(r'''"""Export logic for TextEncode (Phase 4/5 aware)."""
from __future__ import annotations
import io
import json
import pandas as pd
import networkx as nx
from lxml import etree


def _has_table(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _identifiers_grouped(conn) -> dict[str, list[dict]]:
    """entity_id -> list of accepted/recorded identifier dicts."""
    if not (_has_table(conn, "entity_identifiers") and _has_table(conn, "external_authorities")):
        return {}
    rows = conn.execute(
        """
        SELECT ei.entity_id, ea.provider_name, ea.namespace,
               ei.external_identifier, ei.external_uri, ei.external_label,
               ei.match_status, ei.researcher_note, ei.accepted_at
        FROM entity_identifiers ei
        JOIN external_authorities ea ON ea.authority_id = ei.authority_id
        ORDER BY ei.entity_id, ea.provider_name
        """
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(dict(r))
    return grouped


def generate_json_export(conn) -> str:
    tables = {
        "documents": "SELECT * FROM documents WHERE deleted_at IS NULL",
        "passages": "SELECT * FROM passages",
        "entities": "SELECT * FROM entities WHERE deleted_at IS NULL",
        "mentions": "SELECT * FROM mentions WHERE deleted_at IS NULL",
        "relationships": "SELECT * FROM relationships WHERE deleted_at IS NULL",
        "evidence_bundles": "SELECT * FROM evidence_bundles WHERE deleted_at IS NULL",
    }
    data: dict[str, list] = {}
    for name, query in tables.items():
        data[name] = [dict(row) for row in conn.execute(query).fetchall()]

    grouped = _identifiers_grouped(conn)
    if _has_table(conn, "external_authorities"):
        data["external_authorities"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM external_authorities ORDER BY authority_id"
            ).fetchall()
        ]
    data["entity_identifiers"] = [
        ident for ids in grouped.values() for ident in ids
    ]
    # Attach per-entity identifiers (test contract).
    for ent in data["entities"]:
        ent["external_identifiers"] = grouped.get(ent["entity_id"], [])

    return json.dumps(data, ensure_ascii=False, indent=2)


def generate_gephi_data(conn, doc_id: str | None = None):
    if doc_id:
        nodes = conn.execute(
            "SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, "
            "COUNT(m.mention_id) AS mention_count FROM entities e "
            "JOIN entity_categories c ON e.category_id = c.category_id "
            "LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.doc_id = ? "
            "WHERE e.entity_id IN (SELECT entity_id FROM mentions WHERE doc_id = ?) "
            "GROUP BY e.entity_id", (doc_id, doc_id)).fetchall()
        edges = conn.execute(
            "SELECT r.source_entity_id AS source, r.target_entity_id AS target, "
            "rt.name AS type, rt.directed FROM relationships r "
            "JOIN relationship_types rt ON r.type_id = rt.type_id "
            "JOIN mentions m ON r.source_entity_id = m.entity_id WHERE m.doc_id = ?",
            (doc_id,)).fetchall()
    else:
        nodes = conn.execute(
            "SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, "
            "COUNT(m.mention_id) AS mention_count FROM entities e "
            "JOIN entity_categories c ON e.category_id = c.category_id "
            "LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.deleted_at IS NULL "
            "WHERE e.deleted_at IS NULL GROUP BY e.entity_id").fetchall()
        edges = conn.execute(
            "SELECT r.source_entity_id AS source, r.target_entity_id AS target, "
            "rt.name AS type, rt.directed FROM relationships r "
            "JOIN relationship_types rt ON r.type_id = rt.type_id "
            "WHERE r.deleted_at IS NULL").fetchall()
    G = nx.MultiDiGraph()
    for row in nodes:
        G.add_node(row["id"], label=row["label"], category=row["category"],
                   mention_count=row["mention_count"])
    for row in edges:
        G.add_edge(row["source"], row["target"], label=row["type"],
                   directed=bool(row["directed"]))
    buf = io.BytesIO()
    nx.write_gexf(G, buf)
    return (buf.getvalue(),
            pd.DataFrame([dict(r) for r in nodes]).to_csv(index=False).encode("utf-8-sig"),
            pd.DataFrame([dict(r) for r in edges]).to_csv(index=False).encode("utf-8-sig"))


def generate_qgis_geojson(conn) -> str:
    has_ext = _has_table(conn, "entity_identifiers")
    has_geom = conn.execute(
        "SELECT 1 FROM pragma_table_info('entities') WHERE name='geometry_json'"
    ).fetchone() is not None

    cols = "e.entity_id, e.canonical_name, e.latitude, e.longitude, e.geometry_type, e.coordinate_source"
    if has_geom:
        cols += ", e.geometry_json"
    join = " LEFT JOIN entity_identifiers ei ON e.entity_id = ei.entity_id" if has_ext else ""
    grp = " GROUP BY e.entity_id" if has_ext else ""
    ext_sel = ", GROUP_CONCAT(DISTINCT ei.external_uri) AS external_uris" if has_ext else ""
    sql = (
        f"SELECT {cols}{ext_sel} FROM entities e{join} "
        "WHERE e.deleted_at IS NULL AND (e.latitude IS NOT NULL "
        "OR (e.geometry_json IS NOT NULL AND e.geometry_json <> ''))" + grp
    )
    features = []
    for r in conn.execute(sql).fetchall():
        d = dict(r)
        geometry, provenance = None, (d.get("coordinate_source") or "researcher")
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
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "entity_id": d["entity_id"],
                "name": d["canonical_name"],
                "geometry_type": d.get("geometry_type") or geometry.get("type"),
                "coordinate_provenance": provenance,
                "external_uris": d.get("external_uris") or "",
            },
        })
    return json.dumps({"type": "FeatureCollection", "features": features},
                      ensure_ascii=False, indent=2)


def generate_tei_xml(conn, doc_id: str) -> str:
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc:
        return ""
    passages = conn.execute(
        "SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)
    ).fetchall()

    ns = "http://www.tei-c.org/ns/1.0"
    xml_ns = "http://www.w3.org/XML/1998/namespace"
    tei = etree.Element("TEI", nsmap={None: ns})
    header = etree.SubElement(tei, "teiHeader")
    file_desc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(file_desc, "titleStmt")
    etree.SubElement(title_stmt, "title").text = doc["title"]
    pub_stmt = etree.SubElement(file_desc, "publicationStmt")
    etree.SubElement(pub_stmt, "p").text = "Unpublished"
    src_desc = etree.SubElement(file_desc, "sourceDesc")
    etree.SubElement(src_desc, "p").text = doc["original_filename"]

    # --- Phase 4: authority references (idno) in profileDesc ---
    grouped = _identifiers_grouped(conn)
    if grouped:
        profile = etree.SubElement(header, "profileDesc")
        placeholders = ",".join("?" * len(grouped))
        ent_rows = conn.execute(
            f"""SELECT e.entity_id, e.canonical_name, c.name AS category_name
                FROM entities e JOIN entity_categories c ON c.category_id = e.category_id
                WHERE e.entity_id IN ({placeholders})""",
            list(grouped.keys())).fetchall()
        persons = etree.SubElement(profile, "listPerson")
        places = etree.SubElement(profile, "listPlace")
        for er in ent_rows:
            ids = grouped.get(er["entity_id"], [])
            cat = (er["category_name"] or "").lower()
            is_place = any(k in cat for k in ("place", "river", "hydrolog", "ecolog", "geograph"))
            parent, tag, name_tag = (places, "place", "placeName") if is_place else (persons, "person", "persName")
            node = etree.SubElement(parent, tag)
            node.set(f"{{{xml_ns}}}id", er["entity_id"])
            nm = etree.SubElement(node, name_tag)
            nm.text = er["canonical_name"]
            for ident in ids:
                idno = etree.SubElement(node, "idno")
                idno.set("type", ident["namespace"])
                idno.set("source", ident["provider_name"])
                idno.text = ident["external_uri"] or ident["external_identifier"]

    text_el = etree.SubElement(tei, "text")
    body = etree.SubElement(text_el, "body")
    for p in passages:
        p_el = etree.SubElement(body, "p")
        p_el.set(f"{{{xml_ns}}}id", p["passage_id"])
        p_el.text = p["plain_text"]

    return etree.tostring(tei, pretty_print=True, xml_declaration=True,
                          encoding="UTF-8").decode("utf-8")
''', encoding="utf-8")
print("  rewrote exporter.py")

# ---------- verify ----------
print("\n== Verifying syntax... ==")
ok = True
for f in ["app.py", "modules/exporter.py"]:
    try:
        py_compile.compile(str(ROOT / f), doraise=True)
        print(f"  OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"  FAIL: {f}\n{e}")
        ok = False
print("\nDone." if ok else "\nFix the errors above.")
