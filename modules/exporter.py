"""Export logic for TextEncode."""

from __future__ import annotations

import io
import json
import pandas as pd
import networkx as nx
from lxml import etree

def get_all_data_as_dicts(conn) -> dict[str, list[dict]]:
    tables = {
        "documents": "SELECT doc_id, title, author, language, import_date FROM documents",
        "passages": "SELECT passage_id, doc_id, passage_type, sequence, plain_text FROM passages",
        "entity_categories": "SELECT category_id, name, description FROM entity_categories",
        "entities": "SELECT entity_id, canonical_name, category_id, alt_names, description, latitude, longitude FROM entities",
        "mentions": "SELECT mention_id, entity_id, passage_id, surface_form, char_start, char_end, status FROM mentions",
        "relationships": "SELECT relationship_id, source_entity_id, target_entity_id, type_id, description FROM relationships"
    }
    data = {}
    for name, query in tables.items():
        rows = conn.execute(query).fetchall()
        data[name] = [dict(row) for row in rows]
    return data

def generate_json_export(conn) -> str:
    data = get_all_data_as_dicts(conn)
    return json.dumps(data, ensure_ascii=False, indent=2)

def generate_tei_xml(conn, doc_id: str) -> str:
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc: return ""

    passages = conn.execute("SELECT passage_id, plain_text, passage_type, heading_path FROM passages WHERE doc_id = ? ORDER BY sequence", (doc_id,)).fetchall()
    mentions = conn.execute(
        "SELECT m.passage_id, m.surface_form, m.entity_id, c.name as category FROM mentions m "
        "JOIN entities e ON m.entity_id = e.entity_id JOIN entity_categories c ON e.category_id = c.category_id "
        "WHERE m.doc_id = ? AND m.char_start IS NOT NULL", (doc_id,)
    ).fetchall()
    
    mentions_by_passage = {}
    for m in mentions:
        mentions_by_passage.setdefault(m["passage_id"], []).append(m)

    nsmap = {None: "http://www.tei-c.org/ns/1.0"}
    tei = etree.Element("TEI", nsmap=nsmap)
    
    header = etree.SubElement(tei, "teiHeader")
    file_desc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(file_desc, "titleStmt")
    etree.SubElement(title_stmt, "title").text = doc["title"]
    if doc["author"]: etree.SubElement(title_stmt, "author").text = doc["author"]
    pub_stmt = etree.SubElement(file_desc, "publicationStmt")
    etree.SubElement(pub_stmt, "p").text = doc["publication_info"] or "Unpublished"
    source_desc = etree.SubElement(file_desc, "sourceDesc")
    etree.SubElement(source_desc, "p").text = f"Imported from {doc['original_filename']}"

    text_el = etree.SubElement(tei, "text")
    body = etree.SubElement(text_el, "body")
    
    for p in passages:
        tag = "head" if p["passage_type"] == "heading" else "p"
        p_el = etree.SubElement(body, tag)
        p_el.set("{http://www.w3.org/XML/1998/namespace}id", p["passage_id"])
        
        passage_text = p["plain_text"]
        passage_mentions = mentions_by_passage.get(p["passage_id"], [])
        
        if not passage_mentions:
            p_el.text = passage_text
            continue
            
        current_el = p_el
        current_text = passage_text
        
        for m in passage_mentions:
            surface = m["surface_form"]
            if surface not in current_text: continue
                
            parts = current_text.split(surface, 1)
            current_el.text = parts[0]
            
            cat = m["category"].lower()
            tag_name = "persName" if "person" in cat else "placeName" if "place" in cat or "river" in cat else "orgName" if "institution" in cat else "rs"
            
            entity_el = etree.SubElement(p_el, tag_name)
            entity_el.set("ref", f"#{m['entity_id']}")
            entity_el.text = surface
            
            current_el = entity_el
            current_text = parts[1]
            
        current_el.tail = current_text

    standoff = etree.SubElement(tei, "standOff")
    linked_entity_ids = {m["entity_id"] for m in mentions}
    if linked_entity_ids:
        placeholders = ",".join("?" for _ in linked_entity_ids)
        entities = conn.execute(f"SELECT e.entity_id, e.canonical_name, e.description, c.name as category FROM entities e JOIN entity_categories c ON e.category_id = c.category_id WHERE e.entity_id IN ({placeholders})", tuple(linked_entity_ids)).fetchall()
        list_person = etree.SubElement(standoff, "listPerson")
        list_place = etree.SubElement(standoff, "listPlace")
        for e in entities:
            cat = e["category"].lower()
            if "person" in cat:
                person = etree.SubElement(list_person, "person")
                person.set("{http://www.w3.org/XML/1998/namespace}id", e["entity_id"])
                etree.SubElement(person, "persName").text = e["canonical_name"]
            elif "place" in cat or "river" in cat:
                place = etree.SubElement(list_place, "place")
                place.set("{http://www.w3.org/XML/1998/namespace}id", e["entity_id"])
                etree.SubElement(place, "placeName").text = e["canonical_name"]

    return etree.tostring(tei, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")


def generate_gephi_data(conn, doc_id: str | None = None) -> tuple[bytes, bytes, bytes]:
    if doc_id:
        nodes = conn.execute("SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count FROM entities e JOIN entity_categories c ON e.category_id = c.category_id LEFT JOIN mentions m ON e.entity_id = m.entity_id AND m.doc_id = ? WHERE e.entity_id IN (SELECT entity_id FROM mentions WHERE doc_id = ? UNION SELECT source_entity_id FROM relationships WHERE doc_id = ? UNION SELECT target_entity_id FROM relationships WHERE doc_id = ?) GROUP BY e.entity_id", (doc_id, doc_id, doc_id, doc_id)).fetchall()
        edges = conn.execute("SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed, r.evidence_passage_id AS evidence, r.confidence FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id WHERE r.doc_id = ?", (doc_id,)).fetchall()
    else:
        nodes = conn.execute("SELECT e.entity_id AS id, e.canonical_name AS label, c.name AS category, COUNT(m.mention_id) AS mention_count FROM entities e JOIN entity_categories c ON e.category_id = c.category_id LEFT JOIN mentions m ON e.entity_id = m.entity_id GROUP BY e.entity_id").fetchall()
        edges = conn.execute("SELECT r.source_entity_id AS source, r.target_entity_id AS target, rt.name AS type, rt.directed, r.evidence_passage_id AS evidence, r.confidence FROM relationships r JOIN relationship_types rt ON r.type_id = rt.type_id").fetchall()

    G = nx.DiGraph()
    for row in nodes:
        G.add_node(row["id"], label=row["label"], category=row["category"], mention_count=row["mention_count"])
    for row in edges:
        G.add_edge(row["source"], row["target"], label=row["type"], directed=bool(row["directed"]), evidence_passage=row["evidence"] or "", confidence=row["confidence"] or "Unspecified")

    gexf_buffer = io.BytesIO()
    nx.write_gexf(G, gexf_buffer)
    gexf_bytes = gexf_buffer.getvalue()

    nodes_df = pd.DataFrame([dict(r) for r in nodes]) if nodes else pd.DataFrame(columns=["id", "label", "category", "mention_count"])
    edges_df = pd.DataFrame([dict(r) for r in edges]) if edges else pd.DataFrame(columns=["source", "target", "type", "directed", "evidence", "confidence"])

    return gexf_bytes, nodes_df.to_csv(index=False).encode("utf-8-sig"), edges_df.to_csv(index=False).encode("utf-8-sig")


def generate_qgis_geojson(conn) -> str:
    """Generates a GeoJSON FeatureCollection for QGIS."""
    # We only export entities that have actual coordinates
    rows = conn.execute(
        "SELECT e.entity_id, e.canonical_name, c.name as category, e.latitude, e.longitude, "
        "e.geometry_type, e.location_status, e.description, COUNT(m.mention_id) as mention_count "
        "FROM entities e "
        "JOIN entity_categories c ON e.category_id = c.category_id "
        "LEFT JOIN mentions m ON e.entity_id = m.entity_id "
        "WHERE e.latitude IS NOT NULL AND e.longitude IS NOT NULL "
        "GROUP BY e.entity_id"
    ).fetchall()

    features = []
    for r in rows:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",  # For now, we only handle Points for UI input
                "coordinates": [r["longitude"], r["latitude"]]
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

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    return json.dumps(geojson, ensure_ascii=False, indent=2)