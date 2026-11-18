"""TextEncode v0.6 — Research-centred Digital Humanities workstation."""
from __future__ import annotations
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import pydeck as pdk

from database import db
from modules import parser, exporter, ai_recognizer, text_analysis
from ui import theme, components, decorations, settings_page

# ---------------------------------------------------------------------
# APPLICATION INITIALISATION
# ---------------------------------------------------------------------
st.set_page_config(page_title="TextEncode", page_icon="📖", layout="wide", initial_sidebar_state="expanded")

DEFAULTS = {"theme_mode": "Classic Light", "reading_font_size": 1.15, "reading_line_height": 1.8, "reading_width": 800}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

@st.cache_resource
def initialise_database() -> str:
    db.init_db()
    return str(db.DB_PATH)

DB_FILE = initialise_database()
try:
    theme.apply_theme(st.session_state.theme_mode)
except Exception as exc:
    st.warning(f"Theme could not be applied: {exc}")

# ---------------------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------------------
def safe_rerun() -> None:
    st.rerun()

def document_label(document: Any) -> str:
    return f"{document['doc_id']} — {document['title'] or 'Untitled document'}"

def make_document_options(documents: list[Any]) -> dict[str, str]:
    return {document_label(d): d["doc_id"] for d in documents}

def rows_as_dicts(rows: list[Any]) -> list[dict]:
    return [dict(row) for row in rows]

def highlight_mentions(text: str, mentions: list[dict]) -> str:
    if not mentions:
        return html.escape(text)
    valid = []
    for mention in mentions:
        try:
            start, end = int(mention["char_start"]), int(mention["char_end"])
            if 0 <= start < end <= len(text):
                valid.append((start, end, str(mention.get("entity_id", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    valid.sort(key=lambda item: (item[0], item[1]))
    output, cursor = [], 0
    for start, end, entity_id in valid:
        if start < cursor:
            continue
        output.append(html.escape(text[cursor:start]))
        output.append(f"<mark title='{html.escape(entity_id, quote=True)}'>{html.escape(text[start:end])}</mark>")
        cursor = end
    output.append(html.escape(text[cursor:]))
    return "".join(output)

def find_all_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    matches, cursor = [], 0
    while True:
        start = text.find(needle, cursor)
        if start < 0:
            break
        end = start + len(needle)
        matches.append((start, end))
        cursor = end
    return matches

@st.cache_data(show_spinner=False)
def cached_stats(text: str) -> dict:
    return text_analysis.get_basic_stats(text)

@st.cache_data(show_spinner=False)
def cached_frequency(text: str, limit: int) -> list:
    return text_analysis.get_word_frequency(text, limit)

@st.cache_data(show_spinner=False)
def cached_ngrams(text: str, n: int, limit: int) -> list:
    return text_analysis.get_ngrams(text, n, limit)

def render_empty(message: str) -> None:
    components.empty_state(message)

def get_active_profile(conn) -> dict | None:
    profiles = db.list_profiles(conn)
    if not profiles:
        return None
    if "active_profile_id" in st.session_state:
        for p in profiles:
            if p["profile_id"] == st.session_state["active_profile_id"]:
                return dict(p)
    st.session_state["active_profile_id"] = profiles[0]["profile_id"]
    return dict(profiles[0])

def render_profile_selector(conn) -> dict | None:
    profiles = db.list_profiles(conn)
    if not profiles:
        st.error("No taxonomy profile exists. Create one in Taxonomy Manager.")
        return None
    names = {p["name"]: p["profile_id"] for p in profiles}
    current = get_active_profile(conn)
    sel = st.selectbox("Active taxonomy profile", list(names), index=list(names).index(current["name"]) if current else 0, key="global_profile_selector")
    if names[sel] != st.session_state.get("active_profile_id"):
        st.session_state["active_profile_id"] = names[sel]
        st.rerun()
    return get_active_profile(conn)

def _project_document_scope(key_prefix: str):
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
        all_documents = db.list_documents(conn)
    if not all_documents:
        return [], None
    scope_labels = ["All active documents", "One project", "One corpus", "One document"]
    scope = st.selectbox("Analysis scope", scope_labels, key=f"{key_prefix}_scope")
    if scope == "All active documents":
        return all_documents, None
    if scope == "One project":
        if not projects:
            return [], None
        project_options = {f"{p['name']} (Project {p['project_id']})": p["project_id"] for p in projects}
        selected = st.selectbox("Project", list(project_options), key=f"{key_prefix}_project")
        project_id = project_options[selected]
        with db.get_connection() as conn:
            corpora = db.get_corpora(conn, project_id)
        corpus_ids = [c["corpus_id"] for c in corpora]
        return [d for d in all_documents if d["corpus_id"] in corpus_ids], project_id
    if scope == "One corpus":
        corpus_options = {}
        with db.get_connection() as conn:
            for project in projects:
                for corpus in db.get_corpora(conn, project["project_id"]):
                    corpus_options[f"{project['name']} / {corpus['name']} (#{corpus['corpus_id']})"] = corpus["corpus_id"]
        if not corpus_options:
            return [], None
        selected = st.selectbox("Corpus", list(corpus_options), key=f"{key_prefix}_corpus")
        corpus_id = corpus_options[selected]
        return [d for d in all_documents if d["corpus_id"] == corpus_id], corpus_id
    options = make_document_options(all_documents)
    selected = st.selectbox("Document", list(options), key=f"{key_prefix}_document")
    doc_id = options[selected]
    return [d for d in all_documents if d["doc_id"] == doc_id], doc_id

# ---------------------------------------------------------------------
# PAGES
# ---------------------------------------------------------------------
def page_dashboard() -> None:
    components.page_header("Research Dashboard", "An overview of your TextEncode research workspace.")
    decorations.network_ornament()
    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)
        projects = db.get_projects(conn)
    metrics = [{"label": key.replace("_", " ").title(), "value": value} for key, value in stats.items() if key != "categories"]
    components.metric_row(metrics)
    st.divider()
    left, right = st.columns(2)
    left.metric("Research Projects", len(projects))
    right.metric("Active Documents", len(documents))
    st.subheader("Document Library")
    if documents:
        frame = pd.DataFrame(rows_as_dicts(documents))
        columns = [c for c in ["doc_id", "title", "language", "author", "passage_count"] if c in frame.columns]
        st.dataframe(frame[columns], hide_index=True, width="stretch")
    else:
        render_empty("No documents have been imported. Start in Documents.")
    st.caption(f"Database: {DB_FILE}")
    st.divider()
    st.subheader("Data Management")
    st.caption("Create a consistent backup of the research database.")
    if st.button("Create Safe Database Backup", type="primary", key="create_safe_database_backup"):
        try:
            with st.spinner("Creating and verifying database backup..."):
                backup_file = db.create_safe_backup()
                st.session_state["textencode_latest_backup"] = backup_file
                st.success("Database backup created and integrity-checked.")
        except Exception as exc:
            st.error(f"Backup failed: {exc}")
    latest_backup = st.session_state.get("textencode_latest_backup")
    if latest_backup and Path(latest_backup).is_file():
        backup_path = Path(latest_backup)
        st.caption(f"Backup file: {backup_path.name}")
        st.download_button("Download Database Backup", data=backup_path.read_bytes(), file_name=backup_path.name, mime="application/x-sqlite3", key="download_latest_database_backup")

def page_projects() -> None:
    components.page_header(
        "Research Projects",
        "Create, edit, duplicate, move documents between, and recover projects and corpora.",
    )
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
    view_tab, create_tab = st.tabs(["Projects", "Create Project"])
    with create_tab:
        with st.form("create_project_form"):
            name = st.text_input("Project name *")
            desc = st.text_area("Description")
            if st.form_submit_button("Create Project", type="primary"):
                if not name.strip():
                    st.error("Name required.")
                else:
                    with db.get_connection() as conn:
                        pid = db.create_project(conn, name.strip(), desc.strip())
                        db.create_corpus(conn, pid, "Default Corpus", "Initial corpus.")
                    safe_rerun()
    with view_tab:
        if not projects:
            render_empty("No research projects yet.")
            return
        for project in projects:
            pid = project["project_id"]
            with st.expander(f"📁 {project['name']}", expanded=False):
                with st.form(f"edit_project_{pid}"):
                    c1, c2 = st.columns([2, 2])
                    new_name = c1.text_input("Project name", value=project["name"] or "")
                    new_desc = c2.text_area("Description", value=project["description"] or "")
                    b1, b2, b3, b4 = st.columns(4)
                    save = b1.form_submit_button("Save")
                    dup = b2.form_submit_button("Duplicate")
                    trash = b3.form_submit_button("Move to Trash")
                    perm = b4.form_submit_button("Permanent delete")
                if save:
                    with db.get_connection() as conn:
                        db.update_project(conn, pid, new_name, new_desc)
                    safe_rerun()
                if dup:
                    with db.get_connection() as conn:
                        db.duplicate_project(conn, pid, f"{project['name']} (copy)")
                    safe_rerun()
                if trash:
                    with db.get_connection() as conn:
                        db.soft_delete_project(conn, pid)
                    safe_rerun()
                if perm:
                    if not st.session_state.get(f"confirm_perm_proj_{pid}"):
                        st.session_state[f"confirm_perm_proj_{pid}"] = st.checkbox(
                            "I understand: this deletes all corpora and documents in this project",
                            key=f"chk_perm_proj_{pid}",
                        )
                        st.stop()
                    with db.get_connection() as conn:
                        db.hard_delete_project(conn, pid)
                    safe_rerun()

                # Load corpora, docs and move-targets in ONE open connection.
                with db.get_connection() as conn:
                    corpora = db.get_corpora(conn, pid)
                    docs = db.list_documents(conn)
                    move_map: dict[str, int] = {}
                    for p in projects:
                        for c in db.get_corpora(conn, p["project_id"]):
                            move_map[f"{p['name']} / {c['name']} (#{c['corpus_id']})"] = c["corpus_id"]
                move_labels = list(move_map)

                st.markdown("**Corpora & documents**")
                for corpus in corpora:
                    cid = corpus["corpus_id"]
                    with st.container(border=True):
                        with st.form(f"edit_corpus_{cid}"):
                            cc1, cc2 = st.columns([2, 2])
                            c_name = cc1.text_input("Corpus name", value=corpus["name"] or "")
                            c_desc = cc2.text_input("Description", value=corpus["description"] or "")
                            cb1, cb2 = st.columns(2)
                            csave = cb1.form_submit_button("Save corpus")
                            ctrash = cb2.form_submit_button("Trash corpus")
                        if csave:
                            with db.get_connection() as conn:
                                db.update_corpus(conn, cid, c_name, c_desc)
                            safe_rerun()
                        if ctrash:
                            with db.get_connection() as conn:
                                db.soft_delete_corpus(conn, cid)
                            safe_rerun()
                        corpus_docs = [d for d in docs if d["corpus_id"] == cid]
                        if corpus_docs:
                            for d in corpus_docs:
                                mv = st.selectbox(
                                    f"Move {d['doc_id']} to:",
                                    move_labels,
                                    key=f"mv_{d['doc_id']}",
                                )
                                if st.button("Move here", key=f"mvbtn_{d['doc_id']}"):
                                    with db.get_connection() as conn:
                                        db.move_document_to_corpus(conn, d["doc_id"], move_map[mv])
                                    safe_rerun()
                        else:
                            st.caption("No active documents in this corpus.")


def page_documents() -> None:
    components.page_header("Document Library", "Import, inspect, edit and organise research documents.")
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
    if not projects:
        render_empty("Create a research project before importing documents.")
        return
    project_options = {f"{p['name']} (Project {p['project_id']})": p["project_id"] for p in projects}
    selected_project = st.selectbox("Active Project", list(project_options.keys()), key="documents_project")
    project_id = project_options[selected_project]
    with db.get_connection() as conn:
        corpora = db.get_corpora(conn, project_id)
    if not corpora:
        st.warning("This project has no corpus. Create one before importing.")
        return
    corpus_options = {f"{c['name']} (Corpus {c['corpus_id']})": c["corpus_id"] for c in corpora}
    selected_corpus = st.selectbox("Active Corpus", list(corpus_options.keys()), key="documents_corpus")
    corpus_id = corpus_options[selected_corpus]
    import_tab, manage_tab = st.tabs(["Import Documents", "Manage Documents"])
    with import_tab:
        uploaded_files = st.file_uploader("Upload Markdown or plain-text files", type=["md", "markdown", "txt"], accept_multiple_files=True, key="document_upload")
        if not uploaded_files:
            st.info("Select one or more files to import.")
        else:
            batch_language = st.text_input("Default language for this batch", placeholder="e.g. Bengali", key="document_batch_language")
            parsed_items = []
            for uploaded in uploaded_files:
                try:
                    source_text = uploaded.getvalue().decode("utf-8-sig")
                    passages = parser.parse_markdown(source_text)
                    parsed_items.append({"file": uploaded, "source_text": source_text, "passages": passages, "error": None})
                except Exception as exc:
                    parsed_items.append({"file": uploaded, "source_text": None, "passages": None, "error": str(exc)})
            metadata = {}
            for index, item in enumerate(parsed_items):
                with st.expander(item["file"].name, expanded=True):
                    if item["error"]:
                        st.error(item["error"])
                        continue
                    guessed_title = parser.guess_title(item["passages"]) or Path(item["file"].name).stem
                    title = st.text_input("Document title", value=guessed_title, key=f"import_title_{index}")
                    language = st.text_input("Document language", value=batch_language, key=f"import_language_{index}")
                    metadata[index] = {"title": title.strip() or guessed_title, "language": language.strip() or None}
                    st.caption(f"{len(item['passages'])} passages detected.")
            if st.button("Save Documents", type="primary", key="save_document_batch"):
                saved = 0
                for index, item in enumerate(parsed_items):
                    if item["error"] or index not in metadata:
                        continue
                    try:
                        with db.get_connection() as conn:
                            doc_id = db.save_document(conn, title=metadata[index]["title"], original_filename=item["file"].name, source_text=item["source_text"], passages=item["passages"], language=metadata[index]["language"], corpus_id=corpus_id)
                        saved += 1
                        st.success(f"{item['file'].name} imported as {doc_id}.")
                    except Exception as exc:
                        st.error(f"Could not import {item['file'].name}: {exc}")
                if saved:
                    safe_rerun()
    with manage_tab:
        with db.get_connection() as conn:
            documents = db.list_documents(conn, corpus_id)
        if not documents:
            render_empty("This corpus has no active documents.")
        else:
            for document in documents:
                doc_id = document["doc_id"]
                with st.expander(f"📄 {doc_id} — {document['title']}"):
                    st.caption(f"Original file: {document['original_filename']} | Passages: {document['passage_count']}")
                    with st.form(f"edit_document_form_{doc_id}"):
                        title = st.text_input("Title", value=document["title"] or "")
                        author = st.text_input("Author", value=document["author"] or "")
                        language = st.text_input("Language", value=document["language"] or "")
                        publication = st.text_input("Publication information", value=document["publication_info"] or "")
                        save_col, trash_col = st.columns(2)
                        save_clicked = save_col.form_submit_button("Save Changes", type="primary")
                        trash_clicked = trash_col.form_submit_button("Move to Trash")
                    if save_clicked:
                        if not title.strip():
                            st.error("Document title cannot be empty.")
                        else:
                            with db.get_connection() as conn:
                                db.update_document_metadata(conn, doc_id, title.strip(), author.strip(), language.strip(), publication.strip())
                            safe_rerun()
                    if trash_clicked:
                        with db.get_connection() as conn:
                            db.soft_delete_document(conn, doc_id)
                        safe_rerun()

def page_reader() -> None:
    components.page_header("Document Reader", "Read source texts and inspect researcher annotations.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents:
        render_empty("Import a document before opening the reader.")
        return
    options = make_document_options(documents)
    labels = list(options.keys())
    default_index = 0
    previous_doc = st.session_state.get("selected_doc")
    if previous_doc:
        for index, label in enumerate(labels):
            if options[label] == previous_doc:
                default_index = index
                break
    selected_label = st.selectbox("Document", labels, index=default_index, key="reader_document")
    doc_id = options[selected_label]
    st.session_state.selected_doc = doc_id
    with db.get_connection() as conn:
        total_passages = db.count_passages(conn, doc_id)
        mentions = rows_as_dicts(db.get_mentions_for_document(conn, doc_id))
    mentions_by_passage = {}
    for mention in mentions:
        mentions_by_passage.setdefault(mention["passage_id"], []).append(mention)
    if total_passages == 0:
        render_empty("This document contains no parsed passages.")
        return
    reader_col, controls_col = st.columns([4, 1])
    with controls_col:
        st.markdown("### Reader Settings")
        page_count = max(1, math.ceil(total_passages / 25))
        page_number = st.number_input("Page", min_value=1, max_value=page_count, value=1, step=1, key=f"reader_page_{doc_id}")
        show_highlights = st.toggle("Show annotation highlights", value=True, key=f"reader_highlights_{doc_id}")
        st.caption(f"{total_passages} passages")
    with reader_col:
        start = (int(page_number) - 1) * 25
        with db.get_connection() as conn:
            passages = rows_as_dicts(db.get_passages_paginated(conn, doc_id, 25, start))
        for passage in passages:
            text = passage["plain_text"] or ""
            passage_mentions = mentions_by_passage.get(passage["passage_id"], [])
            rendered = highlight_mentions(text, passage_mentions) if show_highlights else html.escape(text)
            st.markdown(f"<div class='reader-container'>{rendered}</div>", unsafe_allow_html=True)
            st.caption(f"{passage['passage_id']} · {passage['passage_type']} · Sequence {passage['sequence']}")

def page_manual_annotation() -> None:
    components.page_header("Manual Annotation", "Register one entity, annotate a passage, and optionally link entities.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
    if not documents or not profiles:
        render_empty("You need at least one document and one taxonomy profile.")
        return
    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        entities = db.get_entities(conn, profile_id)
    register_tab, annotate_tab, link_tab = st.tabs(["Register Single Entity", "Annotate Text", "Link Entities"])
    with register_tab:
        cat_options = {c["name"]: c["category_id"] for c in categories}
        with st.form("manual_register_single_entity"):
            name = st.text_input("Canonical entity name *")
            category = st.selectbox("Category", list(cat_options))
            aliases = st.text_input("Aliases (comma-separated)")
            description = st.text_area("Description")
            create = st.form_submit_button("Register entity", type="primary")
        if create:
            if not name.strip():
                st.error("Entity name is required.")
            else:
                with db.get_connection() as conn:
                    entity_id = db.next_entity_id(conn)
                    conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, alt_names, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (entity_id, profile_id, name.strip(), cat_options[category], aliases.strip() or None, description.strip() or None, db.utc_now()))
                safe_rerun()
    with annotate_tab:
        doc_options = make_document_options(documents)
        doc_label = st.selectbox("Document", list(doc_options), key="manual_doc")
        doc_id = doc_options[doc_label]
        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)
            entities = db.get_entities(conn, profile_id)
        if passages and entities:
            passage_options = {f"{p['passage_id']} · {p['plain_text'][:90]}": p for p in passages}
            passage_label = st.selectbox("Passage", list(passage_options), key="manual_passage")
            passage = passage_options[passage_label]
            passage_text = passage["plain_text"] or ""
            st.text_area("Source passage", passage_text, height=160, disabled=True)
            entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
            with st.form("manual_annotate_single_mention"):
                surface = st.text_input("Exact word or phrase")
                entity_label = st.selectbox("Link mention to entity", list(entity_options))
                occurrences = find_all_occurrences(passage_text, surface.strip()) if surface.strip() else []
                occurrence = st.selectbox("Occurrence", list(range(1, len(occurrences) + 1)) or [1], format_func=lambda x: f"Occurrence {x}")
                note = st.text_area("Research note (optional)")
                save = st.form_submit_button("Save mention", type="primary")
            if save:
                if not occurrences:
                    st.error("That exact word or phrase does not occur in this passage.")
                else:
                    start, end = occurrences[occurrence - 1]
                    with db.get_connection() as conn:
                        db.save_mention(conn, entity_id=entity_options[entity_label], doc_id=doc_id, passage_id=passage["passage_id"], surface_form=surface.strip(), char_start=start, char_end=end, note=note.strip() or None)
                    safe_rerun()
        else:
            st.info("This document needs passages and at least one registered entity.")
    with link_tab:
        with db.get_connection() as conn:
            entities = db.get_entities(conn, profile_id)
            rel_types = db.get_relationship_types(conn, profile_id)
        if len(entities) < 2 or not rel_types:
            st.info("Register at least two entities and relationship types to create a link.")
        else:
            entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
            type_options = {r["name"]: r["type_id"] for r in rel_types}
            doc_options = make_document_options(documents)
            with st.form("manual_optional_entity_link"):
                relationship_doc = st.selectbox("Research document", list(doc_options))
                source = st.selectbox("Source entity", list(entity_options))
                target = st.selectbox("Target entity", list(entity_options))
                relation = st.selectbox("Relationship type", list(type_options))
                description = st.text_area("Description / interpretation")
                link = st.form_submit_button("Create document relationship", type="primary")
            if link:
                if source == target:
                    st.error("Choose two different entities.")
                else:
                    with db.get_connection() as conn:
                        db.save_relationship(conn, entity_options[source], entity_options[target], type_options[relation], description.strip(), doc_id=doc_options[relationship_doc])
                    safe_rerun()

def page_text_analysis() -> None:
    components.page_header("Text Analysis", "Analyse one document, a corpus, a project or all active documents.")
    scoped_docs, scope_id = _project_document_scope("text_analysis")
    if not scoped_docs:
        st.info("The selected scope contains no active documents.")
        return
    texts = []
    with db.get_connection() as conn:
        for document in scoped_docs:
            row = db.get_document(conn, document["doc_id"])
            if row:
                texts.append(row["source_text"] or "")
    full_text = "\n\n".join(texts)
    if not full_text.strip():
        st.info("The selected scope contains no text.")
        return
    st.caption(f"Analysing {len(scoped_docs)} document(s).")
    stats_tab, freq_tab, ngram_tab, kwic_tab = st.tabs(["Overview", "Word Frequency", "N-Grams", "Concordance (KWIC)"])
    with stats_tab:
        stats = cached_stats(full_text)
        components.metric_row([{"label": str(k).replace("_", " ").title(), "value": v} for k, v in stats.items()])
    with freq_tab:
        limit = st.slider("Top terms", 10, 200, 50, 10, key="scoped_freq_limit")
        values = cached_frequency(full_text, limit)
        if values:
            st.dataframe(pd.DataFrame(values, columns=["Term", "Frequency"]), hide_index=True, width="stretch")
        else:
            st.info("No frequency results.")
    with ngram_tab:
        n = st.radio("N-gram size", [2, 3, 4], horizontal=True, key="scoped_ngram_size")
        values = cached_ngrams(full_text, n, 50)
        if values:
            st.dataframe(pd.DataFrame(values, columns=["N-gram", "Frequency"]), hide_index=True, width="stretch")
        else:
            st.info("No n-gram results.")
    with kwic_tab:
        query = st.text_input("Search term", key="scoped_kwic_query")
        if query.strip():
            values = text_analysis.get_kwic(full_text, query.strip())
            if values:
                frame = pd.DataFrame(values)
                cols = [c for c in ["left", "match", "right"] if c in frame.columns]
                st.dataframe(frame[cols], hide_index=True, width="stretch")
            else:
                st.info("No matching contexts found.")

def page_entities() -> None:
    components.page_header("Entity Catalogue", "Manage canonical entities, inspect mentions, and reconcile with external authorities.")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        documents = db.list_documents(conn)
    if not profiles:
        render_empty("Create a taxonomy profile before registering entities.")
        return
    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        entities = db.get_all_entities_with_stats(conn, profile_id)
    if not categories:
        render_empty("The selected taxonomy profile has no categories.")
        return
    category_options = {category["name"]: category["category_id"] for category in categories}
    
    # Added 'external_tab' to the tabs list
    view_tab, add_tab, edit_tab, document_tab, external_tab = st.tabs(
        ["Catalogue", "Add Seed Entity", "Edit Entity", "By Document", "External Identity"]
    )
    
    # --- [Keep your existing view_tab, add_tab, edit_tab, and document_tab code exactly as it was] ---
    # (For brevity, assume the first 4 tabs remain unchanged from your current file)
    # ... (Paste your existing code for view_tab, add_tab, edit_tab, document_tab here) ...

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
            identifiers = db.get_external_identifiers(conn, entity_id)
            candidates = db.get_candidates_for_entity(conn, entity_id, "suggested")
            authorities = db.get_enabled_authorities(conn)
            
        st.markdown("### 1. Accepted Identifiers")
        if identifiers:
            for ident in identifiers:
                with st.container(border=True):
                    st.markdown(f"**{ident['provider_name']}**: [{ident['external_identifier']}]({ident['external_uri']})")
                    st.caption(f"Label: {ident['external_label']} | Status: {ident['match_status']}")
                    if st.button("Detach", key=f"detach_{ident['identifier_id']}"):
                        with db.get_connection() as conn:
                            db.remove_entity_identifier(conn, ident["identifier_id"])
                        st.rerun()
        else:
            st.info("No external identifiers linked yet.")
            
        st.divider()
        st.markdown("### 2. Search External Authorities")
        if not authorities:
            st.warning("No authorities enabled.")
        else:
            auth_options = {a["provider_name"]: a["authority_id"] for a in authorities}
            selected_auth_name = st.selectbox("Provider", list(auth_options.keys()), key="reconcile_auth_select")
            auth_id = auth_options[selected_auth_name]
            
            query = st.text_input("Search Query", key="reconcile_query")
            lang = st.radio("Language", ["en", "bn"], horizontal=True, key="reconcile_lang")
            
            if st.button("Search", type="primary", key="reconcile_search_btn"):
                if not query.strip():
                    st.error("Enter a search query.")
                else:
                    with st.spinner(f"Searching {selected_auth_name}..."):
                        try:
                            if selected_auth_name == "Wikidata":
                                from modules.authorities.wikidata import WikidataProvider
                                provider = WikidataProvider()
                                results = provider.search(query, language=lang)
                            else:
                                st.warning("GeoNames adapter requires configuration. Using Wikidata for demo.")
                                from modules.authorities.wikidata import WikidataProvider
                                provider = WikidataProvider()
                                results = provider.search(query, language=lang)
                                
                            if results:
                                with db.get_connection() as conn:
                                    count = db.save_reconciliation_candidates(conn, entity_id, auth_id, results, query)
                                st.success(f"Found {len(results)} results. {count} new candidates saved.")
                                st.rerun()
                            else:
                                st.info("No results found.")
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
                    st.caption(f"ID: {c['external_identifier']} | URI: {c['external_uri']}")
                    if c['external_description']:
                        st.write(c['external_description'])
                    if c['alternative_names']:
                        st.caption(f"Aliases: {c['alternative_names']}")
                    
                    col1, col2, col3 = st.columns(3)
                    if col1.button("✅ Accept", key=f"acc_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.add_entity_identifier(conn, entity_id, c['authority_id'], c['external_identifier'], c['external_uri'], c['external_label'])
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'accepted')
                        st.rerun()
                    if col2.button("❌ Reject", key=f"rej_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'rejected')
                        st.rerun()
                    if col3.button("⏸️ Defer", key=f"def_{c['candidate_id']}"):
                        with db.get_connection() as conn:
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'deferred')
                        st.rerun()
        else:
            st.info("No pending candidates. Run a search above.")
            
def _centroid_from_coords(coords):
    pts = [c for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return None, None
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lon

def page_spatial_analysis() -> None:
    components.page_header("Spatial Analysis", "Map point, line and polygon entities (rivers, roads, mountain ranges) within a scope.")
    scoped_docs, _ = _project_document_scope("spatial")
    if not scoped_docs:
        st.info("No documents in this scope.")
        return
    doc_ids = [d["doc_id"] for d in scoped_docs]
    ph = ", ".join("?" for _ in doc_ids)
    with db.get_connection() as conn:
        profile = get_active_profile(conn)
        if not profile:
            st.warning("Select a taxonomy profile.")
            return
        entities = conn.execute(f"""SELECT DISTINCT e.entity_id, e.canonical_name, e.latitude, e.longitude, e.geometry_type, e.geometry_json, c.name AS category_name
            FROM entities e JOIN entity_categories c ON c.category_id = e.category_id
            LEFT JOIN mentions m ON m.entity_id = e.entity_id AND m.deleted_at IS NULL
            WHERE e.profile_id = ? AND e.deleted_at IS NULL AND (e.doc_id IN ({ph}) OR m.doc_id IN ({ph}))
            ORDER BY e.canonical_name""", [profile["profile_id"]] + doc_ids + doc_ids).fetchall()
    rows = [dict(e) for e in entities]
    point_rows = [r for r in rows if r["latitude"] is not None and r["longitude"] is not None]
    line_data, poly_data = [], []
    for r in rows:
        if not r["geometry_json"]:
            continue
        try:
            g = json.loads(r["geometry_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if g["type"] in ("LineString",):
            line_data.append({"path": g["coordinates"], "name": r["canonical_name"]})
        elif g["type"] in ("MultiLineString",):
            for seg in g["coordinates"]:
                line_data.append({"path": seg, "name": r["canonical_name"]})
        elif g["type"] == "Polygon":
            poly_data.append({"polygon": g["coordinates"], "name": r["canonical_name"]})
        elif g["type"] == "MultiPolygon":
            for poly in g["coordinates"]:
                poly_data.append({"polygon": poly, "name": r["canonical_name"]})
    layers = []
    if point_rows:
        layers.append(pdk.Layer("ScatterplotLayer", data=point_rows, get_position=["longitude", "latitude"], get_radius=120, get_color=[36, 76, 86], pickable=True))
    if line_data:
        layers.append(pdk.Layer("PathLayer", data=line_data, get_path="path", get_color=[167, 137, 91], width_min_pixels=3))
    if poly_data:
        layers.append(pdk.Layer("PolygonLayer", data=poly_data, get_polygon="polygon", filled=True, get_fill_color=[36, 76, 86, 120], getLineColor=[229, 226, 219]))
    if layers:
        st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=22.98, longitude=87.7, zoom=7, pitch=40)))
    elif point_rows:
        st.map(pd.DataFrame([{"lat": r["latitude"], "lon": r["longitude"]} for r in point_rows]), latitude="lat", longitude="lon")
    else:
        st.info("No georeferenced entities in this scope.")
    st.divider()
    with st.expander("🗺️ Add or edit entity geometry", expanded=True):
        if not rows:
            st.info("No entities in scope.")
            return
        opts = {f"{e['entity_id']} — {e['canonical_name']}": e for e in rows}
        sel = st.selectbox("Entity", list(opts), key="spatial_entity")
        entity = opts[sel]
        gtype = st.selectbox("Geometry type", ["Point", "LineString", "Polygon", "MultiLineString", "MultiPolygon"], index=["Point","LineString","Polygon","MultiLineString","MultiPolygon"].index(entity["geometry_type"] or "Point"), key=f"gt_{entity['entity_id']}")
        if gtype == "Point":
            lat = st.number_input("Latitude", value=float(entity["latitude"] or 0.0), min_value=-90.0, max_value=90.0, format="%.6f")
            lon = st.number_input("Longitude", value=float(entity["longitude"] or 0.0), min_value=-180.0, max_value=180.0, format="%.6f")
            gj = json.dumps({"type": "Point", "coordinates": [lon, lat]})
        else:
            st.caption("Enter one [longitude, latitude] pair per line, e.g. `88.56, 22.33`.")
            default = ""
            if entity["geometry_json"]:
                try:
                    g = json.loads(entity["geometry_json"])
                    coords = g["coordinates"][0] if g["type"].startswith("Multi") or g["type"] == "Polygon" else g["coordinates"]
                    default = "\n".join(f"{c[0]}, {c[1]}" for c in coords if len(c) >= 2)
                except Exception:
                    default = ""
            raw = st.text_area("Coordinates (lon, lat)", value=default, key=f"coords_{entity['entity_id']}", height=160)
            pairs = []
            for ln in raw.splitlines():
                parts = ln.replace("[", "").replace("]", "").split(",")
                if len(parts) >= 2:
                    try:
                        pairs.append([float(parts[0]), float(parts[1])])
                    except ValueError:
                        pass
            if len(pairs) < 2:
                st.error("Provide at least two coordinate pairs for a line/polygon.")
                gj = None
            else:
                if gtype == "Polygon":
                    if pairs[0] != pairs[-1]:
                        pairs.append(pairs[0])
                    gj = json.dumps({"type": "Polygon", "coordinates": [pairs]})
                elif gtype == "LineString":
                    gj = json.dumps({"type": "LineString", "coordinates": pairs})
                else:
                    gj = json.dumps({"type": gtype, "coordinates": [pairs]})
                lat, lon = _centroid_from_coords(pairs)
        if gj and st.button("Save geometry", type="primary", key=f"savegeo_{entity['entity_id']}"):
            try:
                lat_c, lon_c = _centroid_from_coords(json.loads(gj)["coordinates"][0] if gtype != "Point" and not gtype.startswith("Multi") else (json.loads(gj)["coordinates"]))
            except Exception:
                lat_c = lon_c = None
            with db.get_connection() as conn:
                db.set_entity_geometry(conn, entity["entity_id"], gtype, gj, lat_c, lon_c)
            st.success("Geometry saved.")
            safe_rerun()
        if entity["geometry_json"] and st.button("Clear geometry", key=f"clrgeo_{entity['entity_id']}"):
            with db.get_connection() as conn:
                db.set_entity_geometry(conn, entity["entity_id"], "Point", None, None, None)
            safe_rerun()

def page_relationships() -> None:
    components.page_header("Relationship Management", "Researcher-controlled relationships, interpretations and evidence.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profile = get_active_profile(conn)
    if not documents or not profile:
        render_empty("Import documents and select a taxonomy profile first.")
        return
    profile_id = profile["profile_id"]
    with db.get_connection() as conn:
        entities = db.get_entities(conn, profile_id)
        rel_types = db.get_relationship_types(conn, profile_id)
    if len(entities) < 2 or not rel_types:
        render_empty("Register at least two entities and relationship types first.")
        return
    doc_options = make_document_options(documents)
    scope = st.selectbox("Scope", ["Selected document", "Unassigned / legacy", "All active relationships"], key="rel_scope")
    doc_id = None
    if scope == "Selected document":
        doc_id = doc_options[st.selectbox("Research document", list(doc_options), key="rel_doc_v2")]
    scope_key = {"Selected document": "doc", "Unassigned / legacy": "unassigned", "All active relationships": "all"}[scope]
    with db.get_connection() as conn:
        relations = db.list_relationships(conn, scope=scope_key, doc_id=doc_id)
    entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
    entity_labels = list(entity_options)
    type_options = {r["name"]: r["type_id"] for r in rel_types}
    type_names = list(type_options)
    assessments = ["unassessed", "tentative", "supported", "strong", "contested", "rejected"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active", len(relations))
    m2.metric("Document-specific", sum(1 for r in relations if r["doc_id"]))
    m3.metric("Unassigned", sum(1 for r in relations if not r["doc_id"]))
    m4.metric("With evidence", sum(1 for r in relations if r["evidence_count"]))
    st.divider()
    if not relations:
        st.info("No relationships in this scope.")
        return
    for relation in relations:
        rel_id = relation["relationship_id"]
        with st.container(border=True):
            st.markdown(f"**{relation['source_name']}** `[{relation['type_name']}]` **{relation['target_name']}**")
            if relation["description"]:
                st.write(relation["description"])
            st.caption(f"{rel_id} · Doc: {relation['doc_id'] or '🌐 Unassigned'} · Assessment: {relation['research_assessment'] or 'unassessed'} · Evidence: {relation['evidence_count']}")
            src_cur = next((k for k, v in entity_options.items() if v == relation["source_entity_id"]), entity_labels[0])
            tgt_cur = next((k for k, v in entity_options.items() if v == relation["target_entity_id"]), entity_labels[0])
            typ_cur = relation["type_name"] if relation["type_name"] in type_options else type_names[0]
            asmt_cur = relation["research_assessment"] if relation["research_assessment"] in assessments else "unassessed"
            doc_assign = {"🌐 Unassigned / Global": None}
            doc_assign.update(doc_options)
            cur_doc_label = next((k for k, v in doc_assign.items() if v == relation["doc_id"]), "🌐 Unassigned / Global")
            with st.expander("Edit relationship & assign document"):
                with st.form(f"edit_rel_{rel_id}"):
                    e_src = st.selectbox("Source entity", entity_labels, index=entity_labels.index(src_cur))
                    e_tgt = st.selectbox("Target entity", entity_labels, index=entity_labels.index(tgt_cur))
                    e_typ = st.selectbox("Relationship type", type_names, index=type_names.index(typ_cur))
                    e_desc = st.text_area("Description / interpretation", value=relation["description"] or "")
                    e_asmt = st.selectbox("Research assessment", assessments, index=assessments.index(asmt_cur))
                    e_doc = st.selectbox("Document association", list(doc_assign), index=list(doc_assign).index(cur_doc_label))
                    if st.form_submit_button("Save changes", type="primary"):
                        if e_src == e_tgt:
                            st.error("Source and target must differ.")
                        else:
                            with db.get_connection() as conn:
                                db.update_relationship(conn, rel_id, entity_options[e_src], entity_options[e_tgt], type_options[e_typ], e_desc.strip(), doc_id=doc_assign[e_doc], research_assessment=e_asmt)
                            safe_rerun()
            with st.expander("Evidence & provenance"):
                with db.get_connection() as conn:
                    evidence = rows_as_dicts(db.get_evidence_for_relationship(conn, rel_id))
                for item in evidence:
                    with st.container(border=True):
                        st.markdown(f"**{item['evidence_domain']}** · `{item['verification_status'] or 'unverified'}`")
                        st.write(item["source_text"])
                        meta = [p for p in [item.get("author"), item.get("source_title"), item.get("publication_year"), item.get("page_reference"), item.get("url")] if p]
                        if meta:
                            st.caption("📖 " + " | ".join(str(m) for m in meta))
                        if item.get("researcher_note"):
                            st.caption(f"Note: {item['researcher_note']}")
                        if st.button("Soft-delete evidence", key=f"dele_{item['evidence_id']}"):
                            with db.get_connection() as conn:
                                db.soft_delete_evidence(conn, item["evidence_id"])
                            safe_rerun()
                with st.form(f"add_ev_{rel_id}"):
                    dom = st.selectbox("Domain", ["Literary", "Historical", "Geographical"], key=f"dom_{rel_id}")
                    stxt = st.text_area("Evidence passage / source text *", key=f"stxt_{rel_id}")
                    ctx = st.text_input("Context / notes", key=f"ctx_{rel_id}")
                    c1, c2 = st.columns(2)
                    author = c1.text_input("Author", key=f"au_{rel_id}")
                    title = c1.text_input("Title", key=f"ti_{rel_id}")
                    year = c2.text_input("Year", key=f"yr_{rel_id}")
                    pages = c2.text_input("Pages", key=f"pg_{rel_id}")
                    url = st.text_input("URL", key=f"url_{rel_id}")
                    ver = st.selectbox("Verification", ["unverified", "checked", "corroborated", "contested", "rejected"], key=f"ver_{rel_id}")
                    note = st.text_area("Researcher note", key=f"note_{rel_id}")
                    if st.form_submit_button("Attach evidence", type="primary"):
                        if not stxt.strip():
                            st.error("Source text required.")
                        else:
                            with db.get_connection() as conn:
                                db.add_evidence_bundle(conn, rel_id, dom, stxt.strip(), ctx.strip(), author=author.strip() or None, source_title=title.strip() or None, publication_year=year.strip() or None, page_reference=pages.strip() or None, url=url.strip() or None, verification_status=ver, researcher_note=note.strip() or None)
                            safe_rerun()
            st.warning("Moving to Trash hides this relationship but preserves its evidence and provenance.")
            confirm = st.checkbox("Confirm move to Trash", key=f"cf_{rel_id}")
            if st.button("Move relationship to Trash", disabled=not confirm, key=f"tr_{rel_id}"):
                with db.get_connection() as conn:
                    db.soft_delete_relationship(conn, rel_id)
                safe_rerun()
    st.subheader("Add new relationship")
    with st.form("add_rel_v2"):
        a_src = st.selectbox("Source entity", entity_labels)
        a_tgt = st.selectbox("Target entity", entity_labels)
        a_typ = st.selectbox("Relationship type", type_names)
        a_desc = st.text_area("Description / interpretation")
        a_asmt = st.selectbox("Research assessment", assessments)
        a_doc = st.selectbox("Document association", list(doc_assign))
        if st.form_submit_button("Save relationship", type="primary"):
            if a_src == a_tgt:
                st.error("Source and target must differ.")
            else:
                with db.get_connection() as conn:
                    rid = db.save_relationship(conn, entity_options[a_src], entity_options[a_tgt], type_options[a_typ], a_desc.strip(), doc_id=doc_assign[a_doc], research_assessment=a_asmt)
                st.success(f"Saved {rid}.")
                safe_rerun()

def _candidate_phrase_options(passage_text: str, start: int, end: int) -> dict[str, tuple[int, int]]:
    import re
    spans = {}
    if 0 <= start < end <= len(passage_text):
        spans[passage_text[start:end]] = (start, end)
    tokens = list(re.finditer(r"\S+", passage_text))
    overlapping = [i for i, token in enumerate(tokens) if token.start() < end and token.end() > start]
    if overlapping:
        first, last = min(overlapping), max(overlapping)
        for left in range(max(0, first - 2), first + 1):
            for right in range(last, min(len(tokens), last + 3)):
                if right - left + 1 > 5:
                    continue
                phrase_start = tokens[left].start()
                phrase_end = tokens[right].end()
                phrase = passage_text[phrase_start:phrase_end].strip()
                if phrase:
                    spans.setdefault(phrase, (phrase_start, phrase_end))
        for index in range(max(0, first - 2), min(len(tokens), last + 3)):
            token = tokens[index]
            phrase = passage_text[token.start():token.end()]
            spans.setdefault(phrase, (token.start(), token.end()))
    return spans

def page_ai_review() -> None:
    components.page_header("AI Candidate Review", "Choose a suggested word or phrase, then accept, link, reject or defer it.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
    if not documents or not profiles:
        st.info("Import documents and configure a taxonomy profile first.")
        return
    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        entities = db.get_entities(conn, profile_id)
    doc_options = make_document_options(documents)
    selected_doc = st.selectbox("Document", list(doc_options), key="ai_review_doc_v2")
    doc_id = doc_options[selected_doc]
    category_map = {c["name"].lower(): c["category_id"] for c in categories}
    if st.button("Run Entity Recognition", type="primary", key="run_ai_recognition_v2"):
        progress = st.progress(0.0, text="Preparing recognition...")
        try:
            with db.get_connection() as conn:
                passages = db.get_passages(conn, doc_id)
            def progress_update(current, total):
                progress.progress(current / total if total else 1.0, text=f"Scanning passage {current} of {total}")
            found = ai_recognizer.recognize_candidates(passages, category_map, entities, progress_callback=progress_update)
            with db.get_connection() as conn:
                count = db.bulk_save_candidates(conn, found)
            progress.empty()
            st.success(f"{count} candidate(s) added to the review queue.")
            safe_rerun()
        except Exception as exc:
            progress.empty()
            st.error(f"Recognition failed: {exc}")
    with db.get_connection() as conn:
        total = db.count_candidates(conn, doc_id)
        candidates = rows_as_dicts(db.get_candidates_paginated(conn, doc_id, 100, 0))
        entities = db.get_entities(conn, profile_id)
    st.caption(f"{total} pending candidate(s).")
    if not candidates:
        st.info("No pending candidates in this document.")
        return
    categories_by_name = {c["name"]: c["category_id"] for c in categories}
    entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
    for candidate in candidates:
        with st.container(border=True):
            passage_text = candidate["passage_text"] or ""
            start, end = int(candidate["char_start"]), int(candidate["char_end"])
            suggestions = _candidate_phrase_options(passage_text, start, end)
            suggestion_labels = list(suggestions)
            st.markdown(f"**Recognition suggestion:** `{candidate['surface_form']}`")
            st.caption(f"Method: {candidate['recognition_method'] or 'unspecified'} · Confidence: {candidate['confidence_score']}")
            if candidate.get("contextual_evidence"):
                st.write(candidate["contextual_evidence"])
            selected_phrase = st.selectbox("Select a single word or phrase from the suggestions", suggestion_labels, index=(suggestion_labels.index(candidate["surface_form"]) if candidate["surface_form"] in suggestion_labels else 0), key=f"candidate_phrase_{candidate['candidate_id']}")
            phrase_start, phrase_end = suggestions[selected_phrase]
            context_start = max(0, phrase_start - 80)
            context_end = min(len(passage_text), phrase_end + 80)
            st.text(passage_text[context_start:context_end])
            suggested_category = candidate.get("suggested_category_name")
            category_names = list(categories_by_name)
            if not category_names:
                st.warning("No categories exist in the taxonomy.")
                continue
            category_index = category_names.index(suggested_category) if suggested_category in category_names else 0
            category = st.selectbox("Category", category_names, index=category_index, key=f"candidate_category_v2_{candidate['candidate_id']}")
            decision = st.radio("Decision", ["Link to existing entity", "Create new entity", "Reject", "Defer"], horizontal=True, key=f"candidate_decision_{candidate['candidate_id']}")
            linked_entity = None
            new_name = selected_phrase
            if decision == "Link to existing entity":
                if entity_options:
                    linked_entity = st.selectbox("Existing entity", list(entity_options), key=f"candidate_link_entity_{candidate['candidate_id']}")
                else:
                    st.info("No existing entity. Choose Create new entity.")
            elif decision == "Create new entity":
                new_name = st.text_input("Canonical entity name", value=selected_phrase, key=f"candidate_canonical_{candidate['candidate_id']}")
            if st.button("Apply researcher decision", type="primary", key=f"candidate_apply_v2_{candidate['candidate_id']}"):
                if decision == "Defer":
                    st.info("Candidate remains pending.")
                elif decision == "Reject":
                    with db.get_connection() as conn:
                        (conn, candidate["candidate_id"], "rejected")db.update_candidate_status
                    safe_rerun()
                elif decision == "Link to existing entity" and not linked_entity:
                    st.error("Select an existing entity or choose Create new entity.")
                elif decision == "Create new entity" and not new_name.strip():
                    st.error("Canonical entity name cannot be empty.")
                else:
                    try:
                        with db.get_connection() as conn:
                            if decision == "Link to existing entity":
                                entity_id = entity_options[linked_entity]
                            else:
                                entity_id = db.next_entity_id(conn)
                                conn.execute("INSERT INTO entities (entity_id, profile_id, canonical_name, category_id, created_at) VALUES (?, ?, ?, ?, ?)", (entity_id, profile_id, new_name.strip(), categories_by_name[category], db.utc_now()))
                            db.save_mention(conn, entity_id=entity_id, doc_id=doc_id, passage_id=candidate["passage_id"], surface_form=selected_phrase, char_start=phrase_start, char_end=phrase_end)
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'accepted')
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'rejected')
                            db.update_reconciliation_candidate_status(conn, c['candidate_id'], 'deferred')
                        st.success("Selected phrase has been annotated.")
                        safe_rerun()
                    except Exception as exc:
                        st.error(f"Could not save this annotation: {exc}")

def page_trash() -> None:
    components.page_header("Trash & Recovery", "Restore deleted records or permanently remove them after confirmation.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn, include_deleted=True)
        deleted_docs = [d for d in documents if d["deleted_at"] is not None]
        deleted_entities = conn.execute("SELECT * FROM entities WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
        deleted_rels = conn.execute("""SELECT r.relationship_id, r.deleted_at, s.canonical_name AS sn, t.canonical_name AS tn, rt.name AS type_name, r.doc_id
            FROM relationships r JOIN entities s ON s.entity_id=r.source_entity_id JOIN entities t ON t.entity_id=r.target_entity_id JOIN relationship_types rt ON rt.type_id=r.type_id
            WHERE r.deleted_at IS NOT NULL ORDER BY r.deleted_at DESC""").fetchall()
        deleted_profs = db.list_profiles(conn, include_deleted=True)
        deleted_profs = [p for p in deleted_profs if p["deleted_at"] is not None]
    if not deleted_docs and not deleted_entities and not deleted_rels and not deleted_profs:
        render_empty("Trash is empty.")
        return
    if deleted_docs:
        st.subheader("Deleted Documents")
        for document in deleted_docs:
            with st.container(border=True):
                st.markdown(f"**{document['doc_id']} — {document['title']}**")
                st.caption(f"Deleted: {document['deleted_at']}")
                restore_col, delete_col = st.columns(2)
                if restore_col.button("Restore document", key=f"restore_doc_{document['doc_id']}", type="primary"):
                    with db.get_connection() as conn:
                        db.restore_document(conn, document["doc_id"])
                    safe_rerun()
                confirm = delete_col.checkbox("I understand this is irreversible", key=f"confirm_delete_doc_{document['doc_id']}")
                if delete_col.button("Permanently delete", key=f"permanent_doc_{document['doc_id']}", disabled=not confirm):
                    with db.get_connection() as conn:
                        conn.execute("DELETE FROM relationships WHERE doc_id=?", (document["doc_id"],))
                        conn.execute("DELETE FROM entity_candidates WHERE doc_id=?", (document["doc_id"],))
                        db.permanent_delete_document(conn, document["doc_id"])
                    safe_rerun()
    if deleted_entities:
        st.subheader("Deleted Entities")
        for entity in deleted_entities:
            with st.container(border=True):
                st.markdown(f"**{entity['entity_id']} — {entity['canonical_name']}**")
                restore_col, delete_col = st.columns(2)
                if restore_col.button("Restore entity", key=f"restore_ent_{entity['entity_id']}", type="primary"):
                    with db.get_connection() as conn:
                        db.restore_entity(conn, entity["entity_id"])
                    safe_rerun()
                confirm = delete_col.checkbox("I understand this is irreversible", key=f"confirm_delete_ent_{entity['entity_id']}")
                if delete_col.button("Permanently delete entity", key=f"permanent_ent_{entity['entity_id']}", disabled=not confirm):
                    with db.get_connection() as conn:
                        conn.execute("DELETE FROM evidence_bundles WHERE relationship_id IN (SELECT relationship_id FROM relationships WHERE source_entity_id=? OR target_entity_id=?)", (entity["entity_id"], entity["entity_id"]))
                        conn.execute("DELETE FROM relationships WHERE source_entity_id=? OR target_entity_id=?", (entity["entity_id"], entity["entity_id"]))
                        conn.execute("DELETE FROM mentions WHERE entity_id=?", (entity["entity_id"],))
                        conn.execute("DELETE FROM entities WHERE entity_id=?", (entity["entity_id"],))
                    safe_rerun()
    if deleted_rels:
        st.subheader("Deleted Relationships")
        for r in deleted_rels:
            with st.container(border=True):
                st.markdown(f"**{r['sn']}** `[{r['type_name']}]` **{r['tn']}** · {r['relationship_id']}")
                st.caption(f"Doc: {r['doc_id'] or 'Unassigned'} · Deleted: {r['deleted_at']}")
                if st.button("Restore", key=f"rst_rel_{r['relationship_id']}", type="primary"):
                    with db.get_connection() as conn:
                        db.restore_relationship(conn, r["relationship_id"])
                    safe_rerun()
    if deleted_profs:
        st.subheader("Deleted Taxonomy Profiles")
        for p in deleted_profs:
            with st.container(border=True):
                st.markdown(f"**{p['profile_id']} — {p['name']}**")
                if st.button("Restore profile", key=f"rst_prof_{p['profile_id']}", type="primary"):
                    with db.get_connection() as conn:
                        db.restore_profile(conn, p["profile_id"])
                    safe_rerun()

def page_export() -> None:
    components.page_header("Export Centre", "Export structured data for external research tools.")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents:
        render_empty("Import documents before exporting research data.")
        return
    json_tab, tei_tab, network_tab, spatial_tab = st.tabs(["Dataset JSON", "TEI XML", "Network", "Spatial"])
    with json_tab:
        try:
            with db.get_connection() as conn:
                json_data = exporter.generate_json_export(conn)
            st.download_button("Download JSON", data=json_data.encode("utf-8"), file_name="textencode_dataset.json", mime="application/json", type="primary")
        except Exception as exc:
            st.error(f"JSON export failed: {exc}")
    with tei_tab:
        document_options = make_document_options(documents)
        selected = st.selectbox("Document to export", list(document_options.keys()), key="tei_document")
        if st.button("Generate TEI XML", type="primary"):
            try:
                with db.get_connection() as conn:
                    xml_data = exporter.generate_tei_xml(conn, document_options[selected])
                st.download_button("Download TEI XML", data=xml_data.encode("utf-8"), file_name=f"{document_options[selected]}_tei.xml", mime="application/xml")
            except Exception as exc:
                st.error(f"TEI export failed: {exc}")
    with network_tab:
        scope_options = {"All documents / global": None}
        scope_options.update({f"Document: {label}": doc_id for label, doc_id in make_document_options(documents).items()})
        scope = st.selectbox("Network scope", list(scope_options.keys()), key="network_export_scope")
        if st.button("Generate network exports", type="primary"):
            try:
                with db.get_connection() as conn:
                    graph_data, nodes_csv, edges_csv = exporter.generate_gephi_data(conn, scope_options[scope])
                col1, col2, col3 = st.columns(3)
                col1.download_button("Download GEXF", data=graph_data, file_name="textencode_network.gexf", mime="application/gexf+xml", width="stretch")
                col2.download_button("Download Nodes CSV", data=nodes_csv, file_name="textencode_nodes.csv", mime="text/csv", width="stretch")
                col3.download_button("Download Edges CSV", data=edges_csv, file_name="textencode_edges.csv", mime="text/csv", width="stretch")
            except Exception as exc:
                st.error(f"Network export failed: {exc}")
    with spatial_tab:
        if st.button("Generate GeoJSON", type="primary"):
            try:
                with db.get_connection() as conn:
                    geojson_data = exporter.generate_qgis_geojson(conn)
                st.download_button("Download GeoJSON", data=geojson_data.encode("utf-8"), file_name="textencode_spatial_data.geojson", mime="application/geo+json")
            except Exception as exc:
                st.error(f"Spatial export failed: {exc}")

def page_network_analysis() -> None:
    components.page_header("Network Analysis", "Explore researcher-defined entity relationships by document, corpus, project or across the active collection.")
    scoped_docs, _ = _project_document_scope("network")
    if not scoped_docs:
        st.info("No documents in this scope.")
        return
    doc_ids = [d["doc_id"] for d in scoped_docs]
    placeholders = ",".join("?" for _ in doc_ids)
    with db.get_connection() as conn:
        relations = conn.execute(f"""SELECT r.relationship_id, r.source_entity_id, r.target_entity_id, s.canonical_name AS source_name, t.canonical_name AS target_name, rt.name AS type_name, r.description, r.doc_id
            FROM relationships r JOIN entities s ON s.entity_id = r.source_entity_id JOIN entities t ON t.entity_id = r.target_entity_id JOIN relationship_types rt ON rt.type_id = r.type_id
            WHERE r.deleted_at IS NULL AND (r.doc_id IN ({placeholders}) OR r.doc_id IS NULL) ORDER BY r.created_at""", doc_ids).fetchall()
    if not relations:
        st.info("No relationships found in this scope.")
        return
    from streamlit_agraph import agraph, Node, Edge, Config
    nodes, edges = {}, []
    for relation in relations:
        source_id, target_id = relation["source_entity_id"], relation["target_entity_id"]
        nodes.setdefault(source_id, Node(id=source_id, label=relation["source_name"], size=22, color="#244C56"))
        nodes.setdefault(target_id, Node(id=target_id, label=relation["target_name"], size=22, color="#A7895B"))
        edges.append(Edge(source=source_id, target=target_id, label=relation["type_name"], color="#E5E2DB"))
    st.caption(f"{len(scoped_docs)} document(s) · {len(nodes)} entities · {len(edges)} relationship records")
    agraph(nodes=list(nodes.values()), edges=edges, config=Config(width="100%", height=650, directed=True, physics=True, hierarchical=False, nodeHighlightBehavior=True, highlightColor="#F7A7A6", collapsible=False))
    with st.expander("Relationship data"):
        st.dataframe(pd.DataFrame(rows_as_dicts(relations)), hide_index=True, width="stretch")

def page_taxonomy_manager() -> None:
    components.page_header("Taxonomy Manager", "Manage taxonomy profiles, entity categories, relationship types and metadata.")
    with db.get_connection() as conn:
        profiles = db.list_profiles(conn)
    if not profiles:
        st.error("No taxonomy profile found.")
        return
    names = {p["name"]: p["profile_id"] for p in profiles}
    sel = st.selectbox("Active profile", list(names), key="taxonomy_profile")
    profile_id = names[sel]
    with st.expander("✏️ Edit / manage this profile", expanded=False):
        current = next(p for p in profiles if p["profile_id"] == profile_id)
        with st.form(f"edit_profile_{profile_id}"):
            p_name = st.text_input("Profile name", value=current["name"])
            p_desc = st.text_area("Description", value=current["description"] or "")
            p_active = st.checkbox("Active", value=bool(current["is_active"]))
            b1, b2, b3 = st.columns(3)
            psave = b1.form_submit_button("Save profile", type="primary")
            ptrash = b2.form_submit_button("Move to Trash")
            pperm = b3.form_submit_button("Permanent delete")
        if psave:
            with db.get_connection() as conn:
                db.update_profile(conn, profile_id, p_name, p_desc, 1 if p_active else 0)
            safe_rerun()
        if ptrash:
            with db.get_connection() as conn:
                db.soft_delete_profile(conn, profile_id)
            safe_rerun()
        if pperm:
            try:
                with db.get_connection() as conn:
                    db.hard_delete_profile(conn, profile_id)
                safe_rerun()
            except ValueError as exc:
                st.error(str(exc))
    with st.form("new_profile_form"):
        n_name = st.text_input("Create new profile name")
        n_desc = st.text_input("Description")
        if st.form_submit_button("Create profile"):
            if n_name.strip():
                with db.get_connection() as conn:
                    conn.execute("INSERT INTO taxonomy_profiles (name, description, created_at) VALUES (?,?,?)", (n_name.strip(), n_desc.strip() or None, db.utc_now()))
                    npid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    for nm, dsc in db.DEFAULT_CATEGORIES:
                        conn.execute("INSERT INTO entity_categories (profile_id,name,description,is_default) VALUES (?,?,?,1)", (npid, nm, dsc))
                    for nm, dsc, dr in db.DEFAULT_RELATIONSHIP_TYPES:
                        conn.execute("INSERT INTO relationship_types (profile_id,name,description,directed,is_default) VALUES (?,?,?,?,1)", (npid, nm, dsc, dr))
                safe_rerun()
    cat_tab, rel_tab, attr_tab, export_tab = st.tabs(["Entity Categories", "Relationship Types", "Custom Metadata", "Export"])
    with cat_tab:
        with db.get_connection() as conn:
            categories = db.get_categories(conn, profile_id)
        cmap = {c["name"]: c["category_id"] for c in categories}
        with st.form("taxonomy_add_category"):
            name = st.text_input("Category name")
            desc = st.text_input("Description")
            parent = st.selectbox("Parent (optional)", ["None"] + list(cmap))
            add = st.form_submit_button("Add category", type="primary")
        if add and name.strip():
            with db.get_connection() as conn:
                db.save_category(conn, profile_id=profile_id, name=name.strip(), description=desc.strip(), parent_id=cmap.get(parent))
            safe_rerun()
        if categories:
            st.dataframe(pd.DataFrame([dict(c) for c in categories]), hide_index=True, width="stretch")
    with rel_tab:
        with db.get_connection() as conn:
            rtypes = db.get_relationship_types(conn, profile_id)
        with st.form("taxonomy_add_relation_type"):
            name = st.text_input("Relationship type name")
            group = st.text_input("Group", value="General")
            desc = st.text_input("Description")
            directed = st.checkbox("Directed", value=True)
            add = st.form_submit_button("Add type", type="primary")
        if add and name.strip():
            with db.get_connection() as conn:
                db.save_relationship_type(conn, profile_id=profile_id, group_name=group.strip(), name=name.strip(), description=desc.strip(), directed=1 if directed else 0)
            safe_rerun()
        if rtypes:
            st.dataframe(pd.DataFrame([dict(r) for r in rtypes]), hide_index=True, width="stretch")
    with attr_tab:
        with db.get_connection() as conn:
            attrs = db.get_attribute_definitions(conn, profile_id)
        with st.form("taxonomy_add_attribute"):
            target = st.selectbox("Applies to", ["entities", "relationships"])
            name = st.text_input("Attribute name")
            dtype = st.selectbox("Data type", ["text", "integer", "decimal", "date", "boolean", "json"])
            add = st.form_submit_button("Add metadata field", type="primary")
        if add and name.strip():
            with db.get_connection() as conn:
                db.save_attribute_definition(conn, profile_id=profile_id, target_table=target, category_id=None, name=name.strip(), data_type=dtype, description="")
            safe_rerun()
        if attrs:
            st.dataframe(pd.DataFrame([dict(a) for a in attrs]), hide_index=True, width="stretch")
    with export_tab:
        with db.get_connection() as conn:
            prof = dict(conn.execute("SELECT * FROM taxonomy_profiles WHERE profile_id=?", (profile_id,)).fetchone())
            cats = [dict(c) for c in db.get_categories(conn, profile_id)]
            rts = [dict(r) for r in db.get_relationship_types(conn, profile_id)]
            ats = [dict(a) for a in db.get_attribute_definitions(conn, profile_id)]
        payload = {"format": "TextEncodeTaxonomy", "version": 1, "profile": prof, "categories": cats, "relationship_types": rts, "attribute_definitions": ats}
        st.download_button("Download taxonomy JSON", data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), file_name=f"textencode_taxonomy_{profile_id}.json", mime="application/json")

# ---------------------------------------------------------------------
# NAVIGATION
# ---------------------------------------------------------------------
navigation = st.navigation({
    "Workspace": [
        st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:", default=True),
        st.Page(page_projects, title="Projects & Corpora", icon=":material/folder_special:"),
        st.Page(page_documents, title="Documents", icon=":material/folder_open:"),
        st.Page(page_reader, title="Document Reader", icon=":material/menu_book:"),
    ],
    "Analysis": [
        st.Page(page_text_analysis, title="Text Analysis", icon=":material/analytics:"),
        st.Page(page_network_analysis, title="Network Analysis", icon=":material/hub:"),
        st.Page(page_spatial_analysis, title="Spatial Analysis", icon=":material/map:"),
    ],
    "Annotation": [
        st.Page(page_manual_annotation, title="Manual Annotation", icon=":material/edit_note:"),
        st.Page(page_ai_review, title="AI Candidate Review", icon=":material/psychology:"),
        st.Page(page_entities, title="Entity Catalogue", icon=":material/category:"),
        st.Page(page_relationships, title="Relationships", icon=":material/link:"),
    ],
    "Configuration": [
        st.Page(page_taxonomy_manager, title="Taxonomy Manager", icon=":material/account_tree:"),
        st.Page(page_trash, title="Trash & Recovery", icon=":material/delete:"),
        st.Page(page_export, title="Export Centre", icon=":material/download:"),
        st.Page(settings_page.render_settings, title="Settings", icon=":material/settings:"),
    ],
})
navigation.run()