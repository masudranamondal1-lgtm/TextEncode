"""Export logic for TextEncode.

Generates CSV, JSON, and TEI-compatible XML from the SQLite database.
"""

from __future__ import annotations

import json
import pandas as pd
from lxml import etree

def get_all_data_as_dicts(conn) -> dict[str, list[dict]]:
    """Fetch all tables from the database and return them as a dictionary of lists."""
    tables = {
        "documents": "SELECT doc_id, title, author, language, import_date FROM documents",
        "passages": "SELECT passage_id, doc_id, passage_type, sequence, plain_text FROM passages",
        "entity_categories": "SELECT category_id, name, description FROM entity_categories",
        "entities": "SELECT entity_id, canonical_name, category_id, alt_names, description FROM entities",
        "mentions": "SELECT mention_id, entity_id, passage_id, surface_form, status FROM mentions",
        "relationships": "SELECT relationship_id, source_entity_id, target_entity_id, type_id, description FROM relationships"
    }
    data = {}
    for name, query in tables.items():
        rows = conn.execute(query).fetchall()
        data[name] = [dict(row) for row in rows]
    return data


def generate_json_export(conn) -> tuple[str, str]:
    """Returns a tuple of (individual_json_string, combined_json_string)."""
    data = get_all_data_as_dicts(conn)
    
    # Combined JSON
    combined_json = json.dumps(data, ensure_ascii=False, indent=2)
    
    # Individual JSONs (zipped or separate is handled by UI)
    return combined_json


def generate_tei_xml(conn, doc_id: str) -> str:
    """Generate a TEI-compatible XML string for a specific document.
    
    Note: This is a *basic* TEI-compatible export. It is not schema-validated.
    It uses lxml to properly escape characters and structure the document.
    """
    # 1. Fetch Document Metadata
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc:
        return ""

    # 2. Fetch Passages, Mentions, and Entities for this Document
    passages = conn.execute(
        "SELECT passage_id, plain_text, passage_type, heading_path FROM passages WHERE doc_id = ? ORDER BY sequence", 
        (doc_id,)
    ).fetchall()
    
    mentions = conn.execute(
        "SELECT m.passage_id, m.surface_form, m.entity_id, c.name as category "
        "FROM mentions m "
        "JOIN entities e ON m.entity_id = e.entity_id "
        "JOIN entity_categories c ON e.category_id = c.category_id "
        "WHERE m.doc_id = ?", (doc_id,)
    ).fetchall()
    
    # Group mentions by passage_id for easy lookup
    mentions_by_passage = {}
    for m in mentions:
        mentions_by_passage.setdefault(m["passage_id"], []).append(m)

    # 3. Build the XML Tree using lxml
    nsmap = {None: "http://www.tei-c.org/ns/1.0"}
    tei = etree.Element("TEI", nsmap=nsmap)
    
    # --- Header ---
    header = etree.SubElement(tei, "teiHeader")
    file_desc = etree.SubElement(header, "fileDesc")
    title_stmt = etree.SubElement(file_desc, "titleStmt")
    title_el = etree.SubElement(title_stmt, "title")
    title_el.text = doc["title"]
    
    if doc["author"]:
        author_el = etree.SubElement(title_stmt, "author")
        author_el.text = doc["author"]
        
    pub_stmt = etree.SubElement(file_desc, "publicationStmt")
    p_pub = etree.SubElement(pub_stmt, "p")
    p_pub.text = doc["publication_info"] or "Unpublished"
    
    source_desc = etree.SubElement(file_desc, "sourceDesc")
    p_src = etree.SubElement(source_desc, "p")
    p_src.text = f"Imported from {doc['original_filename']} on {doc['import_date']}"

    # --- Text ---
    text_el = etree.SubElement(tei, "text")
    body = etree.SubElement(text_el, "body")
    
    for p in passages:
        # Create a paragraph or heading element
        tag = "head" if p["passage_type"] == "heading" else "p"
        p_el = etree.SubElement(body, tag)
        p_el.set("{http://www.w3.org/XML/1998/namespace}id", p["passage_id"])
        
        passage_text = p["plain_text"]
        passage_mentions = mentions_by_passage.get(p["passage_id"], [])
        
        if not passage_mentions:
            p_el.text = passage_text
            continue
            
        # Mixed content building for inline tags
        # We use a simple split on the first occurrence of the surface form.
        current_el = p_el
        current_text = passage_text
        
        for m in passage_mentions:
            surface = m["surface_form"]
            if surface not in current_text:
                continue
                
            parts = current_text.split(surface, 1)
            current_el.text = parts[0]
            
            # Determine TEI tag based on category
            cat = m["category"].lower()
            tag_name = "rs" # default (referencing string)
            if "person" in cat: tag_name = "persName"
            elif "place" in cat or "river" in cat: tag_name = "placeName"
            elif "institution" in cat: tag_name = "orgName"
            elif "plant" in cat or "animal" in cat or "ecological" in cat: tag_name = "rs"
            
            # Create the inline element with the ref attribute
            entity_el = etree.SubElement(p_el, tag_name)
            entity_el.set("ref", f"#{m['entity_id']}")
            entity_el.text = surface
            
            # Update current pointers for the next loop
            current_el = entity_el
            current_text = parts[1]
            
        current_el.tail = current_text

    # --- StandOff (Entity Lists) ---
    standoff = etree.SubElement(tei, "standOff")
    
    # We only list entities that have mentions in this specific document
    linked_entity_ids = {m["entity_id"] for m in mentions}
    if linked_entity_ids:
        placeholders = ",".join("?" for _ in linked_entity_ids)
        entities = conn.execute(
            f"SELECT e.entity_id, e.canonical_name, e.description, c.name as category "
            f"FROM entities e JOIN entity_categories c ON e.category_id = c.category_id "
            f"WHERE e.entity_id IN ({placeholders})", 
            tuple(linked_entity_ids)
        ).fetchall()
        
        list_person = etree.SubElement(standoff, "listPerson")
        list_place = etree.SubElement(standoff, "listPlace")
        
        for e in entities:
            cat = e["category"].lower()
            if "person" in cat:
                person = etree.SubElement(list_person, "person")
                person.set("{http://www.w3.org/XML/1998/namespace}id", e["entity_id"])
                pers_name = etree.SubElement(person, "persName")
                pers_name.text = e["canonical_name"]
                if e["description"]:
                    note = etree.SubElement(person, "note")
                    note.text = e["description"]
            elif "place" in cat or "river" in cat:
                place = etree.SubElement(list_place, "place")
                place.set("{http://www.w3.org/XML/1998/namespace}id", e["entity_id"])
                place_name = etree.SubElement(place, "placeName")
                place_name.text = e["canonical_name"]
                if e["description"]:
                    note = etree.SubElement(place, "note")
                    note.text = e["description"]

    # Return pretty-printed XML string
    return etree.tostring(tei, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")