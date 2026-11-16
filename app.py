"""TextEncode v0.3.1 — Application Shell & Router."""

from __future__ import annotations
import math
import sys
import html
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from database import db
from modules import parser, processor, exporter, linguistics, taxonomy_ui, ai_recognizer
from ui import theme, components, decorations, settings_page

# 1. Setup Page Config
st.set_page_config(page_title="TextEncode", page_icon="📖", layout="wide")

# 2. Initialize Session State for Themes
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "Classic Light"
if "reading_font_size" not in st.session_state:
    st.session_state.reading_font_size = 1.15
if "reading_line_height" not in st.session_state:
    st.session_state.reading_line_height = 1.8
if "reading_width" not in st.session_state:
    st.session_state.reading_width = 800

# 3. Apply Theme
theme.apply_theme(st.session_state.theme_mode)

# 4. Initialize Database
@st.cache_resource
def _startup() -> str:
    db.init_db()
    return str(db.DB_PATH)

DB_FILE = _startup()

# ==========================================
# HELPERS
# ==========================================
def _document_labels(documents) -> dict[str, str]:
    return {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}

def _passage_rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]

def highlight_mentions(text: str, mentions: list[dict]) -> str:
    safe_text = html.escape(text)
    sorted_mentions = sorted(mentions, key=lambda m: m["char_start"], reverse=True)
    highlighted = safe_text
    for m in sorted_mentions:
        start, end = m["char_start"], m["char_end"]
        if start is not None and end is not None and 0 <= start < end <= len(text):
            if text[start:end] == m["surface_form"]:
                safe_surface = html.escape(m["surface_form"])
                tag = f"<mark title='{html.escape(m['entity_id'])}'>{safe_surface}</mark>"
                highlighted = highlighted.replace(safe_surface, tag, 1)
    return highlighted

# ==========================================
# PAGE VIEWS
# ==========================================

def page_dashboard() -> None:
    components.page_header("Research Dashboard", "Overview of your current workspace.")
    decorations.network_ornament()
    
    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)
        
    components.metric_row([
        {"label": "Documents", "value": stats["documents"]},
        {"label": "Passages", "value": stats["passages"]},
        {"label": "Entities", "value": stats["entities"]},
        {"label": "Mentions", "value": stats["mentions"]},
        {"label": "Relationships", "value": stats["relationships"]}
    ])
    
    st.write("")
    decorations.section_divider()
    st.subheader("Recent Documents")
    
    if documents:
        df = pd.DataFrame([dict(d) for d in documents])[["doc_id", "title", "passage_count"]]
        st.dataframe(df, hide_index=True)
    else:
        components.empty_state("No documents imported yet. Go to Documents to add one.")

def page_documents() -> None:
    components.page_header("Document Library", "Manage imported Markdown texts.")
    
    tab_import, tab_manage = st.tabs(["Import Documents", "Manage Documents"])
    
    with tab_import:
        uploaded = st.file_uploader("Upload Markdown files", type=["md", "markdown", "txt"], accept_multiple_files=True)
        if not uploaded: return
        batch_language = st.text_input("Language for this batch (optional)", placeholder="e.g. Bengali")
        parsed = []
        for f in uploaded:
            try:
                text = f.getvalue().decode("utf-8-sig")
                passages = parser.parse_markdown(text)
                parsed.append({"file": f, "text": text, "passages": passages, "error": None})
            except Exception as exc:
                parsed.append({"file": f, "text": None, "passages": None, "error": str(exc)})

        metadata = {}
        for idx, item in enumerate(parsed):
            with st.expander(f"{item['file'].name}", expanded=True):
                if item["error"]:
                    st.error(item["error"]); continue
                guessed = parser.guess_title(item["passages"]) or Path(item["file"].name).stem
                title = st.text_input("Title", value=guessed, key=f"t_{idx}")
                lang = st.text_input("Language", value=batch_language, key=f"l_{idx}")
                metadata[idx] = {"title": title.strip() or guessed, "language": lang.strip() or None}
                st.caption(f"{len(item['passages'])} passages detected.")

        if st.button("Save to database", type="primary"):
            for idx, item in enumerate(parsed):
                if item["error"]: continue
                with db.get_connection() as conn:
                    try:
                        doc_id = db.save_document(conn, title=metadata[idx]["title"], original_filename=item["file"].name, source_text=item["text"], passages=item["passages"], language=metadata[idx]["language"])
                        st.success(f"Saved {item['file'].name} as {doc_id}.")
                    except Exception as e:
                        st.error(f"Failed to save {item['file'].name}: {e}")
                        
    with tab_manage:
        with db.get_connection() as conn:
            docs = db.list_documents(conn)
        if docs:
            st.dataframe(pd.DataFrame([dict(d) for d in docs]), hide_index=True)
        else:
            components.empty_state("No documents available.")

def page_reader() -> None:
    components.page_header("Document Reader", "Read texts and inspect annotations.")
    
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents: 
        components.empty_state("No documents available.")
        return
        
    doc_id = _document_labels(documents)[st.selectbox("Document", list(_document_labels(documents)))]
    with db.get_connection() as conn:
        total_passages = db.count_passages(conn, doc_id)
        all_mentions = [dict(m) for m in db.get_mentions_for_document(conn, doc_id)]

    mentions_by_passage = {}
    for m in all_mentions:
        mentions_by_passage.setdefault(m["passage_id"], []).append(m)

    col_reader, col_context = st.columns([4, 1])
    
    with col_context:
        st.markdown("### Navigation")
        pages = max(1, math.ceil(total_passages / 25))
        page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1)
        st.caption("Display")
        show_annotations = st.toggle("Show Highlights", value=True)
        
    with col_reader:
        offset = (int(page) - 1) * 25
        with db.get_connection() as conn:
            passages = _passage_rows_to_dicts(db.get_passages_paginated(conn, doc_id, 25, offset))
            
        for p in passages:
            p_mentions = mentions_by_passage.get(p["passage_id"], [])
            if show_annotations:
                highlighted_text = highlight_mentions(p["plain_text"], p_mentions)
            else:
                highlighted_text = html.escape(p["plain_text"])
                
            st.markdown(f"<div class='reader-container'>{highlighted_text}</div><br>", unsafe_allow_html=True)

def page_ai_review() -> None:
    components.page_header("AI Candidate Review", "Verify automatic entity recognition suggestions.")
    
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        existing_entities = db.get_entities(conn, profile_id)

    if not documents: 
        components.empty_state("No documents available.")
        return

    doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
    doc_id = doc_options[st.selectbox("Select Document", list(doc_options.keys()))]

    if st.button("Run Entity Recognition", type="primary"):
        progress_bar = st.progress(0.0, text="Initialising engine...")
        
        def update_progress(current, total):
            progress_bar.progress(current / total, text=f"Scanning: passage {current} of {total}...")

        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)
            categories = db.get_categories(conn, profile_id)
            cat_map = {c["name"].lower(): c["category_id"] for c in categories}
        
        candidates = ai_recognizer.recognize_candidates(passages, cat_map, existing_entities, progress_callback=update_progress)
        
        with db.get_connection() as conn:
            count = db.bulk_save_candidates(conn, candidates)
            
        progress_bar.empty()
        if count > 0: st.success(f"Found and saved {count} new candidates.")
        else: st.info("No new candidates found.")
        st.rerun()

    st.divider()

    with db.get_connection() as conn:
        total_candidates = db.count_candidates(conn, doc_id)
        categories = db.get_categories(conn, profile_id)

    if total_candidates == 0:
        components.empty_state("No pending candidates. Run recognition or check another document.")
        return

    REVIEW_PAGE_SIZE = 15
    total_pages = math.ceil(total_candidates / REVIEW_PAGE_SIZE)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
    offset = (page - 1) * REVIEW_PAGE_SIZE

    with db.get_connection() as conn:
        candidates = db.get_candidates_paginated(conn, doc_id, REVIEW_PAGE_SIZE, offset)

    cat_options = {c["name"]: c["category_id"] for c in categories}
    entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in existing_entities}

    st.subheader(f"Pending Candidates ({total_candidates})")

    h1, h2, h3, h4 = st.columns([3, 3, 3, 2])
    h1.markdown("**Entity / Context**")
    h2.markdown("**Linguistic Evidence**")
    h3.markdown("**Suggested Category**")
    h4.markdown("**Action**")
    st.divider()

    for c in candidates:
        col1, col2, col3, col4 = st.columns([3, 3, 3, 2])
        
        with col1:
            st.markdown(f"### `{c['surface_form']}`")
            context = c['passage_text']
            start, end = c['char_start'], c['char_end']
            snippet_start = max(0, start - 30)
            snippet_end = min(len(context), end + 30)
            snippet = html.escape(context[snippet_start:snippet_end]).replace(html.escape(c['surface_form']), f"**<mark>{html.escape(c['surface_form'])}</mark>**")
            st.markdown(f"...{snippet}...", unsafe_allow_html=True)
            
        with col2:
            st.info(c['contextual_evidence'])
            
        with col3:
            default_cat = c['suggested_category_name'] if c['suggested_category_name'] in cat_options else list(cat_options.keys())[0]
            default_idx = list(cat_options.keys()).index(default_cat)
            cat_name = st.selectbox("Category", list(cat_options.keys()), index=default_idx, key=f"cat_{c['candidate_id']}", label_visibility="collapsed")
            
        with col4:
            if st.button("✔ Accept", key=f"acc_{c['candidate_id']}", type="primary", width="stretch"):
                try:
                    with db.get_connection() as conn:
                        new_entity_id = db.next_entity_id(conn)
                        conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, created_at) VALUES (?, ?, ?, ?, ?)",
                            (new_entity_id, profile_id, c['surface_form'], cat_options[cat_name], db.utc_now()))
                        db.save_mention(conn, entity_id=new_entity_id, doc_id=doc_id, passage_id=c['passage_id'], 
                                        surface_form=c['surface_form'], char_start=c['char_start'], char_end=c['char_end'])
                        db.update_candidate_status(conn, c['candidate_id'], 'accepted')
                    st.rerun()
                except db.OffsetValidationError as e:
                    st.error(f"Error: {e}")
                    
            if st.button("✘ Reject", key=f"rej_{c['candidate_id']}", width="stretch"):
                with db.get_connection() as conn:
                    db.update_candidate_status(conn, c['candidate_id'], 'rejected')
                st.rerun()
        st.divider()

def page_export() -> None:
    components.page_header("Export Centre", "Export structured data for external analysis.")
    
    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if not documents:
        components.empty_state("No data to export yet.")
        return

    tab_data, tab_gephi, tab_qgis = st.tabs(["📄 JSON & TEI", "🕸️ Network (Gephi)", "🗺️ Spatial (QGIS)"])

    with tab_data:
        st.subheader("Full Dataset (JSON)")
        with db.get_connection() as conn:
            combined_json = exporter.generate_json_export(conn)
            st.download_button("📥 Download JSON", data=combined_json.encode("utf-8"), file_name="textencode_dataset.json", mime="application/json", type="primary")
        
        st.divider()
        st.subheader("TEI P5 XML")
        doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
        selected_doc_label = st.selectbox("Select a document to encode as TEI", list(doc_options.keys()))
        if st.button("Generate TEI XML"):
            with db.get_connection() as conn:
                xml_string = exporter.generate_tei_xml(conn, doc_options[selected_doc_label])
            st.download_button("📥 Download TEI XML", data=xml_string.encode("utf-8"), file_name=f"textencode_tei.xml", mime="application/xml")

    with tab_gephi:
        st.subheader("Network Exports")
        scope_options = {"Whole Project": None}
        scope_options.update({f"Only: {d['doc_id']}": d["doc_id"] for d in documents})
        target_doc_id = scope_options[st.selectbox("Export Scope", list(scope_options.keys()))]
        if st.button("Generate Gephi Exports", type="primary"):
            with db.get_connection() as conn:
                gexf_bytes, nodes_csv, edges_csv = exporter.generate_gephi_data(conn, target_doc_id)
            col1, col2, col3 = st.columns(3)
            col1.download_button("📥 GEXF (Graph)", data=gexf_bytes, file_name="network.gexf", mime="application/gexf+xml", width="stretch")
            col2.download_button("📥 Nodes (CSV)", data=nodes_csv, file_name="nodes.csv", mime="text/csv", width="stretch")
            col3.download_button("📥 Edges (CSV)", data=edges_csv, file_name="edges.csv", mime="text/csv", width="stretch")

    with tab_qgis:
        st.subheader("Spatial Exports")
        if st.button("Generate QGIS GeoJSON", type="primary"):
            with db.get_connection() as conn:
                geojson_str = exporter.generate_qgis_geojson(conn)
            st.download_button("📥 Download GeoJSON", data=geojson_str.encode("utf-8"), file_name="textencode_map.geojson", mime="application/geo+json", width="stretch")

# ==========================================
# NAVIGATION & ROUTER
# ==========================================

pg = st.navigation({
    "Workspace": [
        st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:"),
        st.Page(page_documents, title="Documents", icon=":material/folder_open:"),
        st.Page(page_reader, title="Document Reader", icon=":material/menu_book:"),
    ],
    "Annotation": [
        st.Page(page_ai_review, title="AI Candidate Review", icon=":material/psychology:"),
    ],
    "Configuration": [
        st.Page(taxonomy_ui.render_taxonomy_manager, title="Taxonomy Manager", icon=":material/account_tree:"),
        st.Page(page_export, title="Export Centre", icon=":material/download:"),
        st.Page(settings_page.render_settings, title="Settings", icon=":material/settings:"),
    ]
})

pg.run()
