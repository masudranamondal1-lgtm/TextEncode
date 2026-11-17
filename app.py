"""TextEncode v0.5 — Projects, Corpora, and Evidence."""

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
from modules import parser, processor, exporter, linguistics, taxonomy_ui, ai_recognizer, text_analysis
from ui import theme, components, decorations, settings_page, network_page, spatial_page

st.set_page_config(page_title="TextEncode", page_icon="📖", layout="wide")

if "theme_mode" not in st.session_state: st.session_state.theme_mode = "Classic Light"
if "reading_font_size" not in st.session_state: st.session_state.reading_font_size = 1.15
if "reading_line_height" not in st.session_state: st.session_state.reading_line_height = 1.8
if "reading_width" not in st.session_state: st.session_state.reading_width = 800

theme.apply_theme(st.session_state.theme_mode)

@st.cache_resource
def _startup() -> str:
    db.init_db()
    return str(db.DB_PATH)
DB_FILE = _startup()

def _document_labels(documents) -> dict[str, str]:
    return {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}

def _passage_rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]

def highlight_mentions(text: str, mentions: list[dict]) -> str:
    safe_text = html.escape(text)
    if not mentions: return safe_text
    sorted_mentions = sorted(mentions, key=lambda m: m["char_start"], reverse=True)
    highlighted = safe_text
    for m in sorted_mentions:
        start, end = m["char_start"], m["char_end"]
        if start is not None and end is not None and 0 <= start < end <= len(text):
            original_slice = text[start:end]
            safe_slice = html.escape(original_slice)
            idx = highlighted.find(safe_slice)
            if idx != -1:
                tag = f"<mark title='{html.escape(m['entity_id'])}'>{safe_slice}</mark>"
                highlighted = highlighted[:idx] + tag + highlighted[idx+len(safe_slice):]
    return highlighted

@st.cache_data
def _cached_stats(text: str) -> dict: return text_analysis.get_basic_stats(text)
@st.cache_data
def _cached_freq(text: str, limit: int) -> list: return text_analysis.get_word_frequency(text, limit)
@st.cache_data
def _cached_ngrams(text: str, n: int, limit: int) -> list: return text_analysis.get_ngrams(text, n, limit)

def page_dashboard() -> None:
    components.page_header("Research Dashboard", "Overview of your current workspace.")
    decorations.network_ornament()
    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)
    components.metric_row([{"label": k.capitalize(), "value": v} for k, v in stats.items() if k != "categories"])
    st.write("")
    decorations.section_divider()
    st.subheader("Document Library Overview")
    if documents:
        df = pd.DataFrame([dict(d) for d in documents])[["doc_id", "title", "language", "passage_count"]]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        components.empty_state("No documents imported yet. Go to Documents to add one.")

def page_projects() -> None:
    components.page_header("Research Projects", "Organise your corpora.")
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
        
    tab_view, tab_add = st.tabs(["📋 View Projects", "➕ Add Project"])
    
    with tab_view:
        if not projects:
            components.empty_state("No projects yet.")
            return
            
        for p in projects:
            with st.expander(f"📁 {p['name']}"):
                st.write(f"**Description:** {p['description'] or 'None'}")
                with db.get_connection() as conn:
                    corpora = db.get_corpora(conn, p['project_id'])
                st.markdown("**Corpora:**")
                if corpora:
                    for c in corpora:
                        st.write(f"- {c['name']} ({c['description'] or 'No description'})")
                else:
                    st.info("No corpora in this project yet.")
                    
    with tab_add:
        name = st.text_input("Project Name *")
        desc = st.text_area("Description")
        if st.button("Create Project", type="primary"):
            if name.strip():
                with db.get_connection() as conn:
                    pid = db.create_project(conn, name.strip(), desc.strip())
                    db.create_corpus(conn, pid, "Default Corpus", "Initial corpus.")
                st.success("Project created."); st.rerun()
            else:
                st.error("Name required.")

def page_documents() -> None:
    components.page_header("Document Library", "Manage imported Markdown texts.")
    
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
        
    if not projects:
        components.empty_state("No projects available. Create one first.")
        return
        
    project_options = {p["name"]: p["project_id"] for p in projects}
    selected_proj_name = st.selectbox("Active Project", list(project_options.keys()))
    project_id = project_options[selected_proj_name]
    
    with db.get_connection() as conn:
        corpora = db.get_corpora(conn, project_id)
        
    if not corpora:
        st.warning("No corpora in this project. Add one below.")
        with st.form("add_corpus"):
            c_name = st.text_input("Corpus Name")
            if st.form_submit_button("Create Corpus"):
                with db.get_connection() as conn: db.create_corpus(conn, project_id, c_name, "")
                st.rerun()
        return
        
    corpus_options = {c["name"]: c["corpus_id"] for c in corpora}
    selected_corpus_name = st.selectbox("Active Corpus", list(corpus_options.keys()))
    corpus_id = corpus_options[selected_corpus_name]
    
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
                if item["error"]: st.error(item["error"]); continue
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
                        doc_id = db.save_document(conn, title=metadata[idx]["title"], original_filename=item["file"].name, source_text=item["text"], passages=item["passages"], language=metadata[idx]["language"], corpus_id=corpus_id)
                        st.success(f"Saved {item['file'].name} as {doc_id}.")
                    except Exception as e: st.error(f"Failed to save {item['file'].name}: {e}")
                        
    with tab_manage:
        with db.get_connection() as conn: docs = db.list_documents(conn, corpus_id)
        if not docs:
            components.empty_state("This corpus is empty.")
            return
            
        st.write("Expand a document below to edit its metadata or move it to the trash.")
        
        for d in docs:
            with st.expander(f"📄 {d['doc_id']} — {d['title']}"):
                with st.form(f"edit_doc_form_{d['doc_id']}"):
                    new_title = st.text_input("Title", value=d["title"], key=f"title_{d['doc_id']}")
                    new_author = st.text_input("Author", value=d["author"] or "", key=f"author_{d['doc_id']}")
                    new_lang = st.text_input("Language", value=d["language"] or "", key=f"lang_{d['doc_id']}")
                    new_pub = st.text_input("Publication Info", value=d["publication_info"] or "", key=f"pub_{d['doc_id']}")
                    
                    col1, col2 = st.columns(2)
                    if col1.form_submit_button("Save Changes", type="primary"):
                        with db.get_connection() as conn:
                            db.update_document_metadata(conn, d['doc_id'], new_title, new_author, new_lang, new_pub)
                        st.success("Document updated.")
                        st.rerun()
                        
                    if col2.form_submit_button("🗑️ Move to Trash", type="secondary"):
                        with db.get_connection() as conn: db.soft_delete_document(conn, d['doc_id'])
                        st.rerun()

def page_reader() -> None:
    components.page_header("Document Reader", "Read texts and inspect annotations.")
    with db.get_connection() as conn: documents = db.list_documents(conn)
    if not documents: components.empty_state("No documents available."); return
    default_idx = 0
    if "selected_doc" in st.session_state:
        for i, d in enumerate(documents):
            if d["doc_id"] == st.session_state.selected_doc: default_idx = i; break
    labels = _document_labels(documents)
    doc_id = labels[st.selectbox("Document", list(labels.keys()), index=default_idx)]
    with db.get_connection() as conn:
        total_passages = db.count_passages(conn, doc_id)
        all_mentions = [dict(m) for m in db.get_mentions_for_document(conn, doc_id)]
    mentions_by_passage = {}
    for m in all_mentions: mentions_by_passage.setdefault(m["passage_id"], []).append(m)
    col_reader, col_context = st.columns([4, 1])
    with col_context:
        st.markdown("### Navigation")
        pages = max(1, math.ceil(total_passages / 25))
        page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1)
        st.caption("Display")
        show_annotations = st.toggle("Show Highlights", value=True)
    with col_reader:
        offset = (int(page) - 1) * 25
        with db.get_connection() as conn: passages = _passage_rows_to_dicts(db.get_passages_paginated(conn, doc_id, 25, offset))
        for p in passages:
            p_mentions = mentions_by_passage.get(p["passage_id"], [])
            highlighted_text = highlight_mentions(p["plain_text"], p_mentions) if show_annotations else html.escape(p["plain_text"])
            st.markdown(f"<div class='reader-container'>{highlighted_text}</div><br>", unsafe_allow_html=True)

def page_text_analysis() -> None:
    components.page_header("Text Analysis", "Voyant-style exploration of your corpus.")
    with db.get_connection() as conn: documents = db.list_documents(conn)
    if not documents: components.empty_state("No documents available."); return
    doc_options = {"All Documents": None}
    doc_options.update({f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents})
    selected_scope = st.selectbox("Corpus Scope", list(doc_options.keys()))
    doc_id = doc_options[selected_scope]
    with db.get_connection() as conn:
        if doc_id: full_text = db.get_document(conn, doc_id)["source_text"]
        else: full_text = "\n\n".join(conn.execute("SELECT source_text FROM documents WHERE deleted_at IS NULL").fetchall()[i][0] for i in range(len(documents)))
    tab_stats, tab_freq, tab_ngrams, tab_kwic = st.tabs(["Overview", "Word Frequency", "N-Grams", "Concordance (KWIC)"])
    with tab_stats:
        stats = _cached_stats(full_text)
        components.metric_row([{"label": k.replace('_', ' ').title(), "value": v} for k, v in stats.items()])
    with tab_freq:
        limit = st.slider("Top N words", 10, 200, 50, step=10)
        freqs = _cached_freq(full_text, limit)
        if freqs: st.dataframe(pd.DataFrame(freqs, columns=["Word", "Count"]), hide_index=True, width="stretch")
    with tab_ngrams:
        n = st.radio("N-Gram Size", [2, 3, 4], format_func=lambda x: f"{x}-grams", horizontal=True)
        ngrams = _cached_ngrams(full_text, n, 50)
        if ngrams: st.dataframe(pd.DataFrame(ngrams, columns=["N-Gram", "Count"]), hide_index=True, width="stretch")
    with tab_kwic:
        query = st.text_input("Search term for KWIC", placeholder="e.g. ইছামতী")
        if query:
            results = text_analysis.get_kwic(full_text, query)
            if results: st.dataframe(pd.DataFrame(results)[["left", "match", "right"]], hide_index=True, width="stretch")

def page_entities() -> None:
    components.page_header("Entity Catalogue", "Manage your researcher-defined entities and aliases.")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        categories = db.get_categories(conn, profile_id)
        entities = db.get_all_entities_with_stats(conn, profile_id)
    cat_options = {c["name"]: c["category_id"] for c in categories}
    
    tab_view, tab_add, tab_edit = st.tabs(["📋 View Entities", "➕ Add Seed Entity", "✏️ Edit / Delete"])
    
    with tab_view:
        if not entities: components.empty_state("No entities registered yet."); return
        df = pd.DataFrame([dict(e) for e in entities])
        col1, col2 = st.columns([2, 1])
        search = col1.text_input("Search by name or alias")
        filter_cat = col2.selectbox("Filter by category", ["All"] + list(cat_options.keys()))
        if search: df = df[df["canonical_name"].str.contains(search, case=False) | df["alt_names"].fillna("").str.contains(search, case=False)]
        if filter_cat != "All": df = df[df["category_name"] == filter_cat]
        st.dataframe(df[["entity_id", "canonical_name", "alt_names", "category_name", "mention_count"]], hide_index=True, width="stretch")

    with tab_add:
        canonical_name = st.text_input("Canonical Name *")
        category_name = st.selectbox("Category *", list(cat_options.keys()))
        alt_names = st.text_input("Alternative Names (comma separated)")
        description = st.text_area("Description")
        if st.button("Save Entity", type="primary"):
            if not canonical_name.strip(): st.error("Canonical name is required.")
            else:
                with db.get_connection() as conn:
                    new_id = db.next_entity_id(conn)
                    conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, alt_names, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (new_id, profile_id, canonical_name.strip(), cat_options[category_name], alt_names.strip() or None, description.strip() or None, db.utc_now()))
                st.success(f"Entity '{canonical_name}' saved as {new_id}."); st.rerun()

    with tab_edit:
        if not entities: st.info("No entities to edit."); return
        entity_labels = {f"{e['entity_id']} — {e['canonical_name']}": e for e in entities}
        selected_label = st.selectbox("Select entity to manage", list(entity_labels.keys()))
        selected_entity = entity_labels[selected_label]
        
        with st.form("edit_entity_form"):
            e_name = st.text_input("Canonical Name", value=selected_entity["canonical_name"])
            current_cat_idx = list(cat_options.keys()).index(selected_entity["category_name"])
            e_cat = st.selectbox("Category", list(cat_options.keys()), index=current_cat_idx)
            e_alt = st.text_input("Alternative Names", value=selected_entity["alt_names"] or "")
            e_desc = st.text_area("Description", value=selected_entity["description"] or "")
            
            col1, col2 = st.columns(2)
            if col1.form_submit_button("Update Entity", type="primary"):
                with db.get_connection() as conn: db.update_entity_details(conn, selected_entity["entity_id"], e_name.strip(), cat_options[e_cat], e_alt.strip() or None, e_desc.strip() or None)
                st.success("Entity updated."); st.rerun()
            if col2.form_submit_button("🗑️ Move to Trash", type="secondary"):
                with db.get_connection() as conn: db.soft_delete_entity(conn, selected_entity["entity_id"])
                st.warning(f"Moved {selected_entity['entity_id']} to trash."); st.rerun()
                
        st.divider()
        st.subheader("Manage Mentions")
        with db.get_connection() as conn: mentions = db.get_mentions_for_entity(conn, selected_entity["entity_id"])
        if mentions:
            for m in mentions:
                st.markdown(f"**{m['mention_id']}** — `{m['surface_form']}` in {m['passage_id']}")
                st.caption(m['plain_text'][:100] + "...")
                if st.button("Delete Mention", key=f"del_{m['mention_id']}", type="secondary"):
                    with db.get_connection() as conn: db.delete_mention(conn, m['mention_id'])
                    st.rerun()
        else:
            st.info("No mentions found for this entity.")

def page_relationships() -> None:
    components.page_header("Relationship Management", "Connect entities with evidence.")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        entities = db.get_entities(conn, profile_id)
        rel_types = db.get_relationship_types(conn, profile_id)
        rels = db.get_relationships(conn)
        
    if len(entities) < 2:
        components.empty_state("You need at least two entities to create a relationship.")
        return
        
    entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
    type_options = {rt["name"]: rt["type_id"] for rt in rel_types}
    
    tab_view, tab_add = st.tabs(["📋 View Relationships", "➕ Add Relationship"])
    
    with tab_view:
        if not rels: st.info("No relationships yet.")
        else:
            for r in rels:
                with st.container(border=True):
                    st.markdown(f"**{r['source_name']}** `[{r['type_name']}]` **{r['target_name']}**")
                    if r['description']: st.caption(r['description'])
                    
                    with st.expander("Edit Relationship & Manage Evidence"):
                        with st.form(f"edit_rel_{r['relationship_id']}"):
                            src_opts = list(entity_options.keys())
                            tgt_opts = list(entity_options.keys())
                            type_list = list(type_options.keys())
                            
                            current_src = next((k for k, v in entity_options.items() if v == r['source_entity_id']), "[Deleted Entity]")
                            current_tgt = next((k for k, v in entity_options.items() if v == r['target_entity_id']), "[Deleted Entity]")
                            
                            src_idx = src_opts.index(current_src) if current_src in src_opts else 0
                            tgt_idx = tgt_opts.index(current_tgt) if current_tgt in tgt_opts else 0
                            type_idx = type_list.index(r['type_name']) if r['type_name'] in type_list else 0
                            
                            new_src = st.selectbox("Source Entity", src_opts, index=src_idx)
                            new_tgt = st.selectbox("Target Entity", tgt_opts, index=tgt_idx)
                            new_type = st.selectbox("Type", type_list, index=type_idx)
                            new_desc = st.text_area("Description", value=r['description'] or "")
                            
                            col1, col2 = st.columns(2)
                            if col1.form_submit_button("Save Changes", type="primary"):
                                with db.get_connection() as conn:
                                    db.update_relationship(conn, r['relationship_id'], entity_options[new_src], entity_options[new_tgt], type_options[new_type], new_desc)
                                st.success("Updated.")
                                st.rerun()
                            if col2.form_submit_button("🗑️ Delete", type="secondary"):
                                with db.get_connection() as conn: db.delete_relationship(conn, r['relationship_id'])
                                st.rerun()
                                
                        # Evidence Bundle Management
                        st.markdown("**Evidence Bundles**")
                        with db.get_connection() as conn:
                            evidence = db.get_evidence_for_relationship(conn, r['relationship_id'])
                        
                        if evidence:
                            for e in evidence:
                                col_a, col_b = st.columns([4, 1])
                                col_a.markdown(f"**[{e['evidence_domain']}]** {e['source_text']}")
                                if e['context']: col_a.caption(f"Context: {e['context']}")
                                if col_b.button("Delete", key=f"del_ev_{e['evidence_id']}", type="secondary"):
                                    with db.get_connection() as conn: db.delete_evidence_bundle(conn, e['evidence_id'])
                                    st.rerun()
                        else:
                            st.info("No evidence attached yet.")
                            
                        with st.form(f"add_ev_{r['relationship_id']}"):
                            domain = st.selectbox("Evidence Domain", ["Literary", "Historical", "Geographical"])
                            ev_text = st.text_area("Source Text / Evidence *")
                            ev_context = st.text_input("Context / Reference")
                            if st.form_submit_button("Add Evidence Bundle"):
                                if ev_text.strip():
                                    with db.get_connection() as conn:
                                        db.add_evidence_bundle(conn, r['relationship_id'], domain, ev_text.strip(), ev_context.strip())
                                    st.success("Evidence added."); st.rerun()
                                else:
                                    st.error("Evidence text required.")

    with tab_add:
        with st.form("add_relationship"):
            source = st.selectbox("Source Entity", list(entity_options.keys()))
            target = st.selectbox("Target Entity", list(entity_options.keys()))
            rel_type = st.selectbox("Relationship Type", list(type_options.keys()))
            desc = st.text_area("Description / Interpretation")
            if st.form_submit_button("Save Relationship", type="primary"):
                if source == target: st.error("Source and Target must be different.")
                else:
                    with db.get_connection() as conn: db.save_relationship(conn, entity_options[source], entity_options[target], type_options[rel_type], desc)
                    st.success("Relationship saved."); st.rerun()

def page_trash() -> None:
    components.page_header("Trash & Recovery", "Restore or permanently delete data.")
    with db.get_connection() as conn:
        docs = db.list_documents(conn, include_deleted=True)
        deleted_docs = [d for d in docs if d["deleted_at"] is not None]
        entities = conn.execute("SELECT * FROM entities WHERE deleted_at IS NOT NULL").fetchall()
        
    if not deleted_docs and not entities:
        components.empty_state("Trash is empty.")
        return
        
    if deleted_docs:
        st.subheader("Deleted Documents")
        for d in deleted_docs:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 1, 1])
                col1.write(f"**{d['doc_id']}** — {d['title']}")
                col1.caption(f"Deleted at: {d['deleted_at']}")
                if col2.button("♻️ Restore", key=f"restore_{d['doc_id']}", type="primary", width="stretch"):
                    with db.get_connection() as conn: db.restore_document(conn, d['doc_id'])
                    st.rerun()
                confirm = st.checkbox("Confirm permanent deletion", key=f"confirm_{d['doc_id']}")
                if col3.button("❌ Delete Forever", key=f"delete_{d['doc_id']}", disabled=not confirm, type="secondary", width="stretch"):
                    with db.get_connection() as conn: db.permanent_delete_document(conn, d['doc_id'])
                    st.rerun()
                    
    if entities:
        st.subheader("Deleted Entities")
        for e in entities:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                col1.write(f"**{e['entity_id']}** — {e['canonical_name']}")
                if col2.button("♻️ Restore", key=f"restore_{e['entity_id']}", type="primary", width="stretch"):
                    with db.get_connection() as conn: db.restore_entity(conn, e['entity_id'])
                    st.rerun()

def page_ai_review() -> None:
    components.page_header("AI Candidate Review", "Verify automatic entity recognition suggestions.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        existing_entities = db.get_entities(conn, profile_id)
    if not documents: components.empty_state("No documents available."); return
    doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
    doc_id = doc_options[st.selectbox("Select Document", list(doc_options.keys()))]
    if st.button("Run Entity Recognition", type="primary"):
        progress_bar = st.progress(0.0, text="Initialising engine...")
        def update_progress(current, total): progress_bar.progress(current / total, text=f"Scanning: passage {current} of {total}...")
        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)
            categories = db.get_categories(conn, profile_id)
            cat_map = {c["name"].lower(): c["category_id"] for c in categories}
        candidates = ai_recognizer.recognize_candidates(passages, cat_map, existing_entities, progress_callback=update_progress)
        with db.get_connection() as conn: count = db.bulk_save_candidates(conn, candidates)
        progress_bar.empty()
        if count > 0: st.success(f"Found and saved {count} new candidates.")
        else: st.info("No new candidates found.")
        st.rerun()
    st.divider()
    with db.get_connection() as conn:
        total_candidates = db.count_candidates(conn, doc_id)
        categories = db.get_categories(conn, profile_id)
    if total_candidates == 0: components.empty_state("No pending candidates."); return
    REVIEW_PAGE_SIZE = 15
    total_pages = math.ceil(total_candidates / REVIEW_PAGE_SIZE)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
    offset = (page - 1) * REVIEW_PAGE_SIZE
    with db.get_connection() as conn: candidates = db.get_candidates_paginated(conn, doc_id, REVIEW_PAGE_SIZE, offset)
    cat_options = {c["name"]: c["category_id"] for c in categories}
    entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in existing_entities}
    st.subheader(f"Pending Candidates ({total_candidates})")
    h1, h2, h3, h4 = st.columns([3, 3, 3, 2])
    h1.markdown("**Entity / Context**"); h2.markdown("**Linguistic Evidence**"); h3.markdown("**Suggested Category**"); h4.markdown("**Action**")
    st.divider()
    for c in candidates:
        col1, col2, col3, col4 = st.columns([3, 3, 3, 2])
        with col1:
            st.markdown(f"### `{c['surface_form']}`")
            context = c['passage_text']
            start, end = c['char_start'], c['char_end']
            snippet_start = max(0, start - 30); snippet_end = min(len(context), end + 30)
            snippet = html.escape(context[snippet_start:snippet_end]).replace(html.escape(c['surface_form']), f"**<mark>{html.escape(c['surface_form'])}</mark>**")
            st.markdown(f"...{snippet}...", unsafe_allow_html=True)
        with col2: st.info(c['contextual_evidence'])
        with col3:
            default_cat = c['suggested_category_name'] if c['suggested_category_name'] in cat_options else list(cat_options.keys())[0]
            default_idx = list(cat_options.keys()).index(default_cat)
            cat_name = st.selectbox("Category", list(cat_options.keys()), index=default_idx, key=f"cat_{c['candidate_id']}", label_visibility="collapsed")
        with col4:
            if st.button("✔ Accept", key=f"acc_{c['candidate_id']}", type="primary", width="stretch"):
                try:
                    with db.get_connection() as conn:
                        new_entity_id = db.next_entity_id(conn)
                        conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, created_at) VALUES (?, ?, ?, ?, ?)", (new_entity_id, profile_id, c['surface_form'], cat_options[cat_name], db.utc_now()))
                        db.save_mention(conn, entity_id=new_entity_id, doc_id=doc_id, passage_id=c['passage_id'], surface_form=c['surface_form'], char_start=c['char_start'], char_end=c['char_end'])
                        db.update_candidate_status(conn, c['candidate_id'], 'accepted')
                    st.rerun()
                except db.OffsetValidationError as e: st.error(f"Error: {e}")
            if st.button("✘ Reject", key=f"rej_{c['candidate_id']}", width="stretch"):
                with db.get_connection() as conn: db.update_candidate_status(conn, c['candidate_id'], 'rejected')
                st.rerun()
        st.divider()

def page_export() -> None:
    components.page_header("Export Centre", "Export structured data for external analysis.")
    with db.get_connection() as conn: documents = db.list_documents(conn)
    if not documents: components.empty_state("No data to export yet."); return
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
            with db.get_connection() as conn: xml_string = exporter.generate_tei_xml(conn, doc_options[selected_doc_label])
            st.download_button("📥 Download TEI XML", data=xml_string.encode("utf-8"), file_name=f"textencode_tei.xml", mime="application/xml")
    with tab_gephi:
        st.subheader("Network Exports")
        scope_options = {"Whole Project": None}
        scope_options.update({f"Only: {d['doc_id']}": d["doc_id"] for d in documents})
        target_doc_id = scope_options[st.selectbox("Export Scope", list(scope_options.keys()))]
        if st.button("Generate Gephi Exports", type="primary"):
            with db.get_connection() as conn: gexf_bytes, nodes_csv, edges_csv = exporter.generate_gephi_data(conn, target_doc_id)
            col1, col2, col3 = st.columns(3)
            col1.download_button("📥 GEXF (Graph)", data=gexf_bytes, file_name="network.gexf", mime="application/gexf+xml", width="stretch")
            col2.download_button("📥 Nodes (CSV)", data=nodes_csv, file_name="nodes.csv", mime="text/csv", width="stretch")
            col3.download_button("📥 Edges (CSV)", data=edges_csv, file_name="edges.csv", mime="text/csv", width="stretch")
    with tab_qgis:
        st.subheader("Spatial Exports")
        if st.button("Generate QGIS GeoJSON", type="primary"):
            with db.get_connection() as conn: geojson_str = exporter.generate_qgis_geojson(conn)
            st.download_button("📥 Download GeoJSON", data=geojson_str.encode("utf-8"), file_name="textencode_map.geojson", mime="application/geo+json", width="stretch")

pg = st.navigation({
    "Workspace": [
        st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:"),
        st.Page(page_projects, title="Projects & Corpora", icon=":material/folder_special:"),
        st.Page(page_documents, title="Documents", icon=":material/folder_open:"),
        st.Page(page_reader, title="Document Reader", icon=":material/menu_book:"),
    ],
    "Analysis": [
        st.Page(page_text_analysis, title="Text Analysis", icon=":material/analytics:"),
        st.Page(network_page.render_network_analysis, title="Network Analysis", icon=":material/hub:"),
        st.Page(spatial_page.render_spatial_analysis, title="Spatial Analysis", icon=":material/map:"),
    ],
    "Annotation": [
        st.Page(page_entities, title="Entity Catalogue", icon=":material/category:"),
        st.Page(page_relationships, title="Relationships", icon=":material/link:"),
        st.Page(page_ai_review, title="AI Candidate Review", icon=":material/psychology:"),
    ],
    "Configuration": [
        st.Page(taxonomy_ui.render_taxonomy_manager, title="Taxonomy Manager", icon=":material/account_tree:"),
        st.Page(page_trash, title="Trash & Recovery", icon=":material/delete:"),
        st.Page(page_export, title="Export Centre", icon=":material/download:"),
        st.Page(settings_page.render_settings, title="Settings", icon=":material/settings:"),
    ]
})
pg.run()
