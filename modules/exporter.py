"""Export logic for TextEncode."""
from __future__ import annotations
import io
import json
import pandas as pd
import networkx as nx
from lxml import etree

def _has_table(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

def generate_json_export(conn) -> str:
    tables = {
        "documents": "SELECT * FROM documents WHERE deleted_at IS NULL",
        "passages": "SELECT * FROM passages",
        "entities": "SELECT * FROM entities WHERE deleted_at IS NULL",
        "mentions": "SELECT * FROM mentions WHERE deleted_at IS NULL",
        "relationships": "SELECT * FROM relationships WHERE deleted_at IS NULL",
        "evidence_bundles": "SELECT * FROM evidence_bundles WHERE deleted_at IS NULL",
    }
    data = {}
    for name, query in tables.items():
        data[name] = [dict(row) for row in conn.execute(query).fetchall()]
    
    if _has_table(conn, "external_authorities"):
        data["external_authorities"] = [dict(r) for r in conn.execute("SELECT * FROM external_authorities").fetchall()]
        data["entity_identifiers"] = [dict(r) for r in conn.execute("""
            SELECT ei.*, ea.provider_name FROM entity_identifiers ei 
            JOIN external_authorities ea ON ei.authority_id = ea.authority_id
        """).fetchall()]
        
    return json.dumps(data, ensure_ascii=False, indent=2)

def generate_gephi_data(conn, doc_id: str | None = None) -> tuple[bytes, bytes, bytes]:
    if doc_id:
        nodes = conn.execute("SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count FROM entities e JOIN entity_categories c ON e.category_id = c.category_id LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.doc_id = ? WHERE e.entity_id IN (SELECT entity_id FROM mentions WHERE doc_id = ?) GROUP BY e.entity_id", (doc_id, doc_id)).fetchall()
        edges = conn.execute("SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id JOIN mentions m ON r.source_entity_id = m.entity_id WHERE m.doc_id = ?", (doc_id,)).fetchall()
    else:
        nodes = conn.execute("SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count FROM entities e JOIN entity_categories c ON e.category_id = c.category_id LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.deleted_at IS NULL WHERE e.deleted_at IS NULL GROUP BY e.entity_id").fetchall()
        edges = conn.execute("SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id WHERE r.deleted_at IS NULL").fetchall()
    G = nx.MultiDiGraph()
    for row in nodes: G.add_node(row["id"], label=row["label"], category=row["category"], mention_count=row["mention_count"])
    for row in edges: G.add_edge(row["source"], row["target"], label=row["type"], directed=bool(row["directed"]))
    gexf_buffer = io.BytesIO()
    nx.write_gexf(G, gexf_buffer)
    return gexf_buffer.getvalue(), pd.DataFrame([dict(r) for r in nodes]).to_csv(index=False).encode("utf-8-sig"), pd.DataFrame([dict(r) for r in edges]).to_csv(index=False).encode("utf-8-sig")

def generate_qgis_geojson(conn) -> str:
    rows = conn.execute("""
        SELECT e.entity_id, e.canonical_name, e.latitude, e.longitude, e.category_id, e.coordinate_source,
               GROUP_CONCAT(DISTINCT ei.external_uri) as authority_uris
        FROM entities e 
        LEFT JOIN entity_identifiers ei ON e.entity_id = ei.entity_id
        WHERE e.latitude IS NOT NULL AND e.longitude IS NOT NULL AND e.deleted_at IS NULL 
        GROUP BY e.entity_id
    """).fetchall()
    features = []
    for r in rows:
        features.append({
            "type": "Feature", 
            "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]}, 
            "properties": {
                "entity_id": r["entity_id"], 
                "name": r["canonical_name"], 
                "category_id": r["category_id"],
                "coordinate_source": r["coordinate_source"] or "researcher",
                "authority_uris": r["authority_uris"] or ""
            }
        })
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)

def generate_tei_xml(conn, doc_id: str) -> str:
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc: return ""
    passages = conn.execute("SELECT * FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
    nsmap = {None: "http://www.tei-c.org/ns/1.0"}
    tei = etree.Element("TEI", nsmap=nsmap)
    header = etree.SubElement(tei, "teiHeader")
    file_desc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(file_desc, "titleStmt")
    etree.SubElement(title_stmt, "title").text = doc["title"]
    pub_stmt = etree.SubElement(file_desc, "publicationStmt")
    etree.SubElement(pub_stmt, "p").text = "Unpublished"
    text_el = etree.SubElement(tei, "text")
    body = etree.SubElement(text_el, "body")
    for p in passages:
        p_el = etree.SubElement(body, "p")
        p_el.set("{http://www.w3.org/XML/1998/namespace}id", p["passage_id"])
        p_el.text = p["plain_text"]
    return etree.tostring(tei, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")
