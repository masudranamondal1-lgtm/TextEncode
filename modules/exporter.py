"""Export logic for TextEncode."""

from __future__ import annotations
import io
import json
import pandas as pd
import networkx as nx
from lxml import etree

def generate_json_export(conn) -> str:
    """Generates a complete JSON dump of the database."""
    tables = {
        "documents": "SELECT doc_id, title, author, language, import_date FROM documents",
        "passages": "SELECT passage_id, doc_id, passage_type, sequence, plain_text FROM passages",
        "entities": "SELECT e.*, c.name as category_name FROM entities e JOIN entity_categories c ON e.category_id = c.category_id",
        "mentions": "SELECT * FROM mentions",
        "relationships": "SELECT r.*, rt.name as relationship_name FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id",
        "attribute_values": "SELECT av.*, ad.name as attribute_name FROM attribute_values av JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id"
    }
    data = {}
    for name, query in tables.items():
        rows = conn.execute(query).fetchall()
        data[name] = [dict(row) for row in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)


def generate_gephi_data(conn, doc_id: str | None = None) -> tuple[bytes, bytes, bytes]:
    """Generates GEXF, Nodes CSV, and Edges CSV with custom metadata included."""
    if doc_id:
        nodes = conn.execute("""
            SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count 
            FROM entities e JOIN entity_categories c ON e.category_id = c.category_id 
            LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.doc_id = ? 
            WHERE e.entity_id IN (SELECT entity_id FROM mentions WHERE doc_id = ? UNION SELECT source_entity_id FROM relationships WHERE doc_id = ? UNION SELECT target_entity_id FROM relationships WHERE doc_id = ?) 
            GROUP BY e.entity_id
        """, (doc_id, doc_id, doc_id, doc_id)).fetchall()
        edges = conn.execute("""
            SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed, r.evidence_passage_id AS evidence, r.confidence 
            FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id WHERE r.doc_id = ?
        """, (doc_id,)).fetchall()
    else:
        nodes = conn.execute("""
            SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count 
            FROM entities e JOIN entity_categories c ON e.category_id = c.category_id 
            LEFT JOIN mentions m ON e.entity_id = m.entity_id GROUP BY e.entity_id
        """).fetchall()
        edges = conn.execute("""
            SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed, r.evidence_passage_id AS evidence, r.confidence 
            FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id
        """).fetchall()

    # Fetch custom attributes for nodes
    attributes = conn.execute("SELECT entity_id, value_text FROM attribute_values av JOIN attribute_definitions ad ON av.attribute_id = ad.attribute_id").fetchall()
    attr_map = {}
    for a in attributes:
        attr_map.setdefault(a["entity_id"], []).append(a["value_text"])

    G = nx.DiGraph()
    for row in nodes:
        custom_meta = "; ".join(attr_map.get(row["id"], []))
        G.add_node(row["id"], label=row["label"], category=row["category"], mention_count=row["mention_count"], custom_metadata=custom_meta)
        
    for row in edges:
        G.add_edge(row["source"], row["target"], label=row["type"], directed=bool(row["directed"]), evidence=row["evidence"] or "", confidence=row["confidence"] or "")

    gexf_buffer = io.BytesIO()
    nx.write_gexf(G, gexf_buffer)
    
    nodes_df = pd.DataFrame([dict(r) for r in nodes])
    edges_df = pd.DataFrame([dict(r) for r in edges])

    return gexf_buffer.getvalue(), nodes_df.to_csv(index=False).encode("utf-8-sig"), edges_df.to_csv(index=False).encode("utf-8-sig")


def generate_qgis_geojson(conn) -> str:
    """Generates a valid GeoJSON FeatureCollection for QGIS."""
    # Fetch entities with spatial data
    rows = conn.execute("""
        SELECT e.entity_id, e.canonical_name, c.name as category, e.latitude, e.longitude, 
               e.geometry_type, e.location_status, e.description, COUNT(m.mention_id) as mention_count
        FROM entities e JOIN entity_categories c ON e.category_id = c.category_id
        LEFT JOIN mentions m ON e.entity_id = m.entity_id
        WHERE e.latitude IS NOT NULL AND e.longitude IS NOT NULL
        GROUP BY e.entity_id
    """).fetchall()

    features = []
    for r in rows:
        # Currently, the UI only supports Points. If you add polygon/line support later, parse WKT here.
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point", 
                "coordinates": [r["longitude"], r["latitude"]] # GeoJSON is always [Longitude, Latitude]
            },
            "properties": {
                "entity_id": r["entity_id"],
                "name": r["canonical_name"],
                "category": r["category"],
                "location_status": r["location_status"],
                "mention_count": r["mention_count"],
                "description": r["description"] or ""
            }
        }
        features.append(feature)

    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2)


def generate_tei_xml(conn, doc_id: str) -> str:
    """Generate TEI P5 XML with stand-off annotations."""
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc: return ""

    passages = conn.execute("SELECT passage_id, plain_text, passage_type FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
    
    nsmap = {None: "http://www.tei-c.org/ns/1.0"}
    tei = etree.Element("TEI", nsmap=nsmap)
    
    header = etree.SubElement(tei, "teiHeader")
    file_desc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(file_desc, "titleStmt")
    etree.SubElement(title_stmt, "title").text = doc["title"]
    source_desc = etree.SubElement(file_desc, "sourceDesc")
    etree.SubElement(source_desc, "p").text = f"Imported from {doc['original_filename']}"

    text_el = etree.SubElement(tei, "text")
    body = etree.SubElement(text_el, "body")
    
    for p in passages:
        tag = "head" if p["passage_type"] == "heading" else "p"
        p_el = etree.SubElement(body, tag)
        p_el.set("{http://www.w3.org/XML/1998/namespace}id", p["passage_id"])
        p_el.text = p["plain_text"]

    # StandOff Annotation
    standoff = etree.SubElement(tei, "standOff")
    list_entity = etree.SubElement(standoff, "listAnnotation")
    
    mentions = conn.execute("""
        SELECT m.mention_id, m.surface_form, m.char_start, m.char_end, m.passage_id, m.entity_id 
        FROM mentions m WHERE m.doc_id = ?
    """, (doc_id,)).fetchall()
    
    for m in mentions:
        ann = etree.SubElement(list_entity, "annotation")
        ann.set("xml:id", m["mention_id"])
        ann.set("corresp", f"#{m['entity_id']}")
        span = etree.SubElement(ann, "span")
        span.set("from", f"#{m['passage_id']}")
        span.set("start", str(m["char_start"]))
        span.set("end", str(m["char_end"]))
        span.text = m["surface_form"]

    return etree.tostring(tei, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")