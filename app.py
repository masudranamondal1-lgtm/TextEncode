"""TextEncode v0.6 — Research-centred Digital Humanities workstation.

This app is designed to work with the existing TextEncode database layer.
It deliberately avoids destructive schema changes. Back up textencode.db
before upgrading or experimenting with this file.
"""

from __future__ import annotations

import html
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from database import db
from modules import (
    parser,
    exporter,
    ai_recognizer,
    text_analysis,
    taxonomy_ui,
)
from ui import (
    theme,
    components,
    decorations,
    settings_page,
    network_page,
    spatial_page,
)


# ---------------------------------------------------------------------
# APPLICATION INITIALISATION
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="TextEncode",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULTS = {
    "theme_mode": "Classic Light",
    "reading_font_size": 1.15,
    "reading_line_height": 1.8,
    "reading_width": 800,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


@st.cache_resource
def initialise_database() -> str:
    """Initialise the existing database once per Streamlit process."""
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
    """Rerun using the Streamlit API available in the installed version."""
    st.rerun()


def document_label(document: Any) -> str:
    title = document["title"] or "Untitled document"
    return f"{document['doc_id']} — {title}"


def make_document_options(documents: list[Any]) -> dict[str, str]:
    return {document_label(d): d["doc_id"] for d in documents}


def rows_as_dicts(rows: list[Any]) -> list[dict]:
    return [dict(row) for row in rows]


def get_default_profile(conn) -> tuple[int, list[Any], list[Any]]:
    """Return the first configured taxonomy profile and its categories."""
    profiles = db.get_profiles(conn)
    if not profiles:
        raise RuntimeError(
            "No taxonomy profile exists. Open Taxonomy Manager and create one."
        )
    profile_id = profiles[0]["profile_id"]
    categories = db.get_categories(conn, profile_id)
    relationship_types = db.get_relationship_types(conn, profile_id)
    return profile_id, categories, relationship_types


def highlight_mentions(text: str, mentions: list[dict]) -> str:
    """Safely highlight valid, non-overlapping offsets in a passage."""
    if not mentions:
        return html.escape(text)

    valid = []
    for mention in mentions:
        try:
            start = int(mention["char_start"])
            end = int(mention["char_end"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= start < end <= len(text):
            valid.append((start, end, str(mention.get("entity_id", ""))))

    valid.sort(key=lambda item: (item[0], item[1]))

    output: list[str] = []
    cursor = 0
    for start, end, entity_id in valid:
        # Overlapping annotations are retained in the database but only the
        # first non-overlapping interval is highlighted in this reader view.
        if start < cursor:
            continue
        output.append(html.escape(text[cursor:start]))
        output.append(
            "<mark title='{}'>{}</mark>".format(
                html.escape(entity_id, quote=True),
                html.escape(text[start:end]),
            )
        )
        cursor = end

    output.append(html.escape(text[cursor:]))
    return "".join(output)


def find_all_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    """Find exact, non-overlapping occurrences without normalising source text."""
    if not needle:
        return []
    matches = []
    cursor = 0
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


def scoped_entity_rows(conn, profile_id: int, doc_id: str | None = None) -> list[Any]:
    """List entities with mention counts, optionally within one document.

    Canonical entities remain reusable. A document-specific mention links an
    entity to a passage in that document.
    """
    if doc_id:
        return conn.execute(
            """
            SELECT
                e.entity_id,
                e.canonical_name,
                e.alt_names,
                e.description,
                c.name AS category_name,
                COUNT(m.mention_id) AS mention_count
            FROM entities e
            JOIN entity_categories c ON c.category_id = e.category_id
            LEFT JOIN mentions m
                ON m.entity_id = e.entity_id
                AND m.doc_id = ?
                AND m.deleted_at IS NULL
            WHERE e.profile_id = ?
              AND e.deleted_at IS NULL
            GROUP BY e.entity_id
            ORDER BY mention_count DESC, e.canonical_name COLLATE NOCASE
            """,
            (doc_id, profile_id),
        ).fetchall()

    return db.get_all_entities_with_stats(conn, profile_id)


def scoped_relationship_rows(conn, doc_id: str | None = None) -> list[Any]:
    """Return relationships, optionally restricted to one document.

    Legacy relationships with a NULL doc_id are shown only in the
    unfiltered/global view. New relationships created in this app are scoped.
    """
    base = """
        SELECT
            r.relationship_id,
            r.source_entity_id,
            r.target_entity_id,
            s.canonical_name AS source_name,
            t.canonical_name AS target_name,
            rt.name AS type_name,
            r.description,
            r.doc_id,
            r.confidence,
            r.note
        FROM relationships r
        JOIN entities s ON s.entity_id = r.source_entity_id
        JOIN entities t ON t.entity_id = r.target_entity_id
        JOIN relationship_types rt ON rt.type_id = r.type_id
        WHERE r.deleted_at IS NULL
    """
    if doc_id:
        return conn.execute(
            base + " AND r.doc_id = ? ORDER BY r.created_at DESC",
            (doc_id,),
        ).fetchall()
    return conn.execute(base + " ORDER BY r.created_at DESC").fetchall()


def render_empty(message: str) -> None:
    components.empty_state(message)


# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------

def page_dashboard() -> None:
    components.page_header(
        "Research Dashboard",
        "An overview of your TextEncode research workspace.",
    )
    decorations.network_ornament()

    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)
        projects = db.get_projects(conn)

    metrics = [
        {"label": key.replace("_", " ").title(), "value": value}
        for key, value in stats.items()
        if key != "categories"
    ]
    components.metric_row(metrics)

    st.divider()
    left, right = st.columns(2)
    left.metric("Research Projects", len(projects))
    right.metric("Active Documents", len(documents))

    st.subheader("Document Library")
    if documents:
        frame = pd.DataFrame(rows_as_dicts(documents))
        columns = [
            c for c in
            ["doc_id", "title", "language", "author", "passage_count"]
            if c in frame.columns
        ]
        st.dataframe(frame[columns], hide_index=True, width="stretch")
    else:
        render_empty("No documents have been imported. Start in Documents.")

    st.caption(f"Database: {DB_FILE}")


# ---------------------------------------------------------------------
# PROJECTS AND CORPORA
# ---------------------------------------------------------------------

def page_projects() -> None:
    components.page_header(
        "Research Projects",
        "Organise documents into projects and corpora.",
    )

    with db.get_connection() as conn:
        projects = db.get_projects(conn)

    view_tab, create_tab = st.tabs(["Projects", "Create Project"])

    with view_tab:
        if not projects:
            render_empty("No research projects have been created.")
        else:
            for project in projects:
                with st.expander(f"📁 {project['name']}"):
                    st.write(project["description"] or "No description.")
                    with db.get_connection() as conn:
                        corpora = db.get_corpora(conn, project["project_id"])
                    if corpora:
                        st.dataframe(
                            pd.DataFrame(rows_as_dicts(corpora)),
                            hide_index=True,
                            width="stretch",
                        )
                    else:
                        st.info("This project has no corpora yet.")

    with create_tab:
        with st.form("create_project_form"):
            name = st.text_input("Project name *")
            description = st.text_area("Description")
            submitted = st.form_submit_button(
                "Create Project",
                type="primary",
            )

        if submitted:
            if not name.strip():
                st.error("A project name is required.")
            else:
                with db.get_connection() as conn:
                    project_id = db.create_project(
                        conn,
                        name.strip(),
                        description.strip(),
                    )
                    db.create_corpus(
                        conn,
                        project_id,
                        "Default Corpus",
                        "Initial corpus.",
                    )
                st.success("Project and default corpus created.")
                safe_rerun()

        st.caption(
            "A project is a research container. A corpus groups documents "
            "within that project."
        )


# ---------------------------------------------------------------------
# DOCUMENT LIBRARY
# ---------------------------------------------------------------------

def page_documents() -> None:
    components.page_header(
        "Document Library",
        "Import, inspect, edit and organise research documents.",
    )

    with db.get_connection() as conn:
        projects = db.get_projects(conn)

    if not projects:
        render_empty("Create a research project before importing documents.")
        return

    project_options = {
        f"{p['name']} (Project {p['project_id']})": p["project_id"]
        for p in projects
    }
    selected_project = st.selectbox(
        "Active Project",
        list(project_options.keys()),
        key="documents_project",
    )
    project_id = project_options[selected_project]

    with db.get_connection() as conn:
        corpora = db.get_corpora(conn, project_id)

    if not corpora:
        st.warning("This project has no corpus. Create one before importing.")
        return

    corpus_options = {
        f"{c['name']} (Corpus {c['corpus_id']})": c["corpus_id"]
        for c in corpora
    }
    selected_corpus = st.selectbox(
        "Active Corpus",
        list(corpus_options.keys()),
        key="documents_corpus",
    )
    corpus_id = corpus_options[selected_corpus]

    import_tab, manage_tab = st.tabs(
        ["Import Documents", "Manage Documents"]
    )

    # Import tab. No return here: it must not prevent Manage Documents rendering.
    with import_tab:
        uploaded_files = st.file_uploader(
            "Upload Markdown or plain-text files",
            type=["md", "markdown", "txt"],
            accept_multiple_files=True,
            key="document_upload",
        )

        if not uploaded_files:
            st.info(
                "Select one or more files to import. Existing documents "
                "remain available in Manage Documents."
            )
        else:
            batch_language = st.text_input(
                "Default language for this batch",
                placeholder="e.g. Bengali",
                key="document_batch_language",
            )

            parsed_items: list[dict] = []
            for uploaded in uploaded_files:
                try:
                    source_text = uploaded.getvalue().decode("utf-8-sig")
                    passages = parser.parse_markdown(source_text)
                    parsed_items.append(
                        {
                            "file": uploaded,
                            "source_text": source_text,
                            "passages": passages,
                            "error": None,
                        }
                    )
                except Exception as exc:
                    parsed_items.append(
                        {
                            "file": uploaded,
                            "source_text": None,
                            "passages": None,
                            "error": str(exc),
                        }
                    )

            metadata: dict[int, dict] = {}
            for index, item in enumerate(parsed_items):
                with st.expander(item["file"].name, expanded=True):
                    if item["error"]:
                        st.error(item["error"])
                        continue

                    guessed_title = (
                        parser.guess_title(item["passages"])
                        or Path(item["file"].name).stem
                    )
                    title = st.text_input(
                        "Document title",
                        value=guessed_title,
                        key=f"import_title_{index}",
                    )
                    language = st.text_input(
                        "Document language",
                        value=batch_language,
                        key=f"import_language_{index}",
                    )
                    metadata[index] = {
                        "title": title.strip() or guessed_title,
                        "language": language.strip() or None,
                    }
                    st.caption(
                        f"{len(item['passages'])} passages detected."
                    )

            if st.button(
                "Save Documents",
                type="primary",
                key="save_document_batch",
            ):
                saved = 0
                for index, item in enumerate(parsed_items):
                    if item["error"]:
                        continue
                    if index not in metadata:
                        st.error(
                            f"Metadata missing for {item['file'].name}; "
                            "that file was skipped."
                        )
                        continue

                    try:
                        with db.get_connection() as conn:
                            doc_id = db.save_document(
                                conn,
                                title=metadata[index]["title"],
                                original_filename=item["file"].name,
                                source_text=item["source_text"],
                                passages=item["passages"],
                                language=metadata[index]["language"],
                                corpus_id=corpus_id,
                            )
                        saved += 1
                        st.success(
                            f"{item['file'].name} imported as {doc_id}."
                        )
                    except Exception as exc:
                        st.error(
                            f"Could not import {item['file'].name}: {exc}"
                        )

                if saved:
                    st.success(f"{saved} document(s) imported.")
                    safe_rerun()

    # Manage tab is independent of the uploader state.
    with manage_tab:
        with db.get_connection() as conn:
            documents = db.list_documents(conn, corpus_id)

        if not documents:
            render_empty("This corpus has no active documents.")
        else:
            st.write(
                "Edit document metadata or move a document to Trash. "
                "Moving to Trash does not permanently erase its content."
            )

            for document in documents:
                doc_id = document["doc_id"]
                with st.expander(
                    f"📄 {doc_id} — {document['title']}"
                ):
                    st.caption(
                        f"Original file: {document['original_filename']} | "
                        f"Passages: {document['passage_count']}"
                    )

                    with st.form(f"edit_document_form_{doc_id}"):
                        title = st.text_input(
                            "Title",
                            value=document["title"] or "",
                        )
                        author = st.text_input(
                            "Author",
                            value=document["author"] or "",
                        )
                        language = st.text_input(
                            "Language",
                            value=document["language"] or "",
                        )
                        publication = st.text_input(
                            "Publication information",
                            value=document["publication_info"] or "",
                        )

                        save_col, trash_col = st.columns(2)
                        save_clicked = save_col.form_submit_button(
                            "Save Changes",
                            type="primary",
                        )
                        trash_clicked = trash_col.form_submit_button(
                            "Move to Trash",
                        )

                    if save_clicked:
                        if not title.strip():
                            st.error("Document title cannot be empty.")
                        else:
                            with db.get_connection() as conn:
                                db.update_document_metadata(
                                    conn,
                                    doc_id,
                                    title.strip(),
                                    author.strip(),
                                    language.strip(),
                                    publication.strip(),
                                )
                            st.success("Document metadata updated.")
                            safe_rerun()

                    if trash_clicked:
                        with db.get_connection() as conn:
                            db.soft_delete_document(conn, doc_id)
                        st.warning(f"{doc_id} moved to Trash.")
                        safe_rerun()


# ---------------------------------------------------------------------
# DOCUMENT READER
# ---------------------------------------------------------------------

def page_reader() -> None:
    components.page_header(
        "Document Reader",
        "Read source texts and inspect researcher annotations.",
    )

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

    selected_label = st.selectbox(
        "Document",
        labels,
        index=default_index,
        key="reader_document",
    )
    doc_id = options[selected_label]
    st.session_state.selected_doc = doc_id

    with db.get_connection() as conn:
        document = db.get_document(conn, doc_id)
        total_passages = db.count_passages(conn, doc_id)
        mentions = rows_as_dicts(
            db.get_mentions_for_document(conn, doc_id)
        )

    mentions_by_passage: dict[str, list[dict]] = {}
    for mention in mentions:
        mentions_by_passage.setdefault(
            mention["passage_id"], []
        ).append(mention)

    if total_passages == 0:
        render_empty("This document contains no parsed passages.")
        return

    reader_col, controls_col = st.columns([4, 1])

    with controls_col:
        st.markdown("### Reader Settings")
        page_count = max(1, math.ceil(total_passages / 25))
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=page_count,
            value=1,
            step=1,
            key=f"reader_page_{doc_id}",
        )
        show_highlights = st.toggle(
            "Show annotation highlights",
            value=True,
            key=f"reader_highlights_{doc_id}",
        )
        st.caption(f"{total_passages} passages")

    with reader_col:
        start = (int(page_number) - 1) * 25
        with db.get_connection() as conn:
            passages = rows_as_dicts(
                db.get_passages_paginated(
                    conn,
                    doc_id,
                    25,
                    start,
                )
            )

        for passage in passages:
            text = passage["plain_text"] or ""
            passage_mentions = mentions_by_passage.get(
                passage["passage_id"], []
            )
            rendered = (
                highlight_mentions(text, passage_mentions)
                if show_highlights
                else html.escape(text)
            )
            st.markdown(
                f"<div class='reader-container'>{rendered}</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"{passage['passage_id']} · "
                f"{passage['passage_type']} · "
                f"Sequence {passage['sequence']}"
            )


# ---------------------------------------------------------------------
# MANUAL ANNOTATION
# ---------------------------------------------------------------------

def page_manual_annotation() -> None:
    components.page_header(
        "Manual Annotation",
        "Create evidence-linked mentions in a selected document.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)

    if not documents:
        render_empty("Import a document before annotating.")
        return
    if not profiles:
        render_empty("Create a taxonomy profile before annotating.")
        return

    profile_id = profiles[0]["profile_id"]
    doc_options = make_document_options(documents)
    selected_doc_label = st.selectbox(
        "1. Select document",
        list(doc_options.keys()),
        key="manual_annotation_document",
    )
    doc_id = doc_options[selected_doc_label]

    with db.get_connection() as conn:
        passages = db.get_passages(conn, doc_id)
        entities = db.get_entities(conn, profile_id)

    if not passages:
        render_empty("No passages are available in this document.")
        return
    if not entities:
        st.warning(
            "There are no registered entities. Add a seed entity in "
            "Entity Catalogue first."
        )
        return

    passage_options = {
        f"{p['passage_id']} · {str(p['plain_text'])[:100]}":
            p["passage_id"]
        for p in passages
    }
    selected_passage_label = st.selectbox(
        "2. Select passage",
        list(passage_options.keys()),
        key="manual_annotation_passage",
    )
    passage_id = passage_options[selected_passage_label]
    passage = next(p for p in passages if p["passage_id"] == passage_id)
    passage_text = passage["plain_text"] or ""

    st.text_area(
        "Passage text (read-only reference)",
        value=passage_text,
        height=180,
        disabled=True,
    )

    entity_options = {
        f"{e['entity_id']} — {e['canonical_name']}":
            e["entity_id"]
        for e in entities
    }

    with st.form("manual_annotation_form"):
        surface = st.text_input(
            "3. Exact text to annotate",
            help="Copy an exact substring from the passage.",
        )
        entity_label = st.selectbox(
            "4. Link to canonical entity",
            list(entity_options.keys()),
        )
        occurrence_choice = st.selectbox(
            "Occurrence",
            ["First occurrence", "Second occurrence", "Third occurrence",
             "Fourth occurrence", "Fifth occurrence"],
        )
        note = st.text_area("Research note (optional)")
        submitted = st.form_submit_button(
            "Save Annotation",
            type="primary",
        )

    if submitted:
        needle = surface.strip()
        if not needle:
            st.error("Enter the exact text to annotate.")
        else:
            matches = find_all_occurrences(passage_text, needle)
            occurrence_index = [
                "First occurrence",
                "Second occurrence",
                "Third occurrence",
                "Fourth occurrence",
                "Fifth occurrence",
            ].index(occurrence_choice)

            if not matches:
                st.error(
                    "The exact text was not found in this passage. "
                    "Check punctuation, spacing and Bengali characters."
                )
            elif occurrence_index >= len(matches):
                st.error(
                    f"Only {len(matches)} occurrence(s) were found. "
                    "Choose an available occurrence."
                )
            else:
                start, end = matches[occurrence_index]
                try:
                    with db.get_connection() as conn:
                        mention_id = db.save_mention(
                            conn,
                            entity_id=entity_options[entity_label],
                            doc_id=doc_id,
                            passage_id=passage_id,
                            surface_form=needle,
                            char_start=start,
                            char_end=end,
                            note=note.strip() or None,
                        )
                    st.success(
                        f"Annotation saved: {mention_id}"
                    )
                    safe_rerun()
                except Exception as exc:
                    st.error(f"Could not save annotation: {exc}")


# ---------------------------------------------------------------------
# TEXT ANALYSIS
# ---------------------------------------------------------------------

def page_text_analysis() -> None:
    components.page_header(
        "Text Analysis",
        "Corpus exploration: frequency, n-grams, statistics and KWIC.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if not documents:
        render_empty("Import documents before running text analysis.")
        return

    options: dict[str, str | None] = {"All active documents": None}
    options.update(make_document_options(documents))

    selected_scope = st.selectbox(
        "Analysis scope",
        list(options.keys()),
        key="text_analysis_scope",
    )
    doc_id = options[selected_scope]

    with db.get_connection() as conn:
        if doc_id:
            document = db.get_document(conn, doc_id)
            full_text = document["source_text"] if document else ""
        else:
            rows = conn.execute(
                """
                SELECT source_text
                FROM documents
                WHERE deleted_at IS NULL
                ORDER BY doc_id
                """
            ).fetchall()
            full_text = "\n\n".join(row["source_text"] or "" for row in rows)

    if not full_text.strip():
        st.info("The selected scope contains no text.")
        return

    stats_tab, frequency_tab, ngram_tab, kwic_tab = st.tabs(
        ["Overview", "Word Frequency", "N-Grams", "Concordance (KWIC)"]
    )

    with stats_tab:
        stats = cached_stats(full_text)
        components.metric_row(
            [
                {
                    "label": str(key).replace("_", " ").title(),
                    "value": value,
                }
                for key, value in stats.items()
            ]
        )

    with frequency_tab:
        limit = st.slider(
            "Number of terms",
            min_value=10,
            max_value=200,
            value=50,
            step=10,
            key="frequency_limit",
        )
        frequencies = cached_frequency(full_text, limit)
        if frequencies:
            st.dataframe(
                pd.DataFrame(
                    frequencies,
                    columns=["Term", "Frequency"],
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No frequency results were returned.")

    with ngram_tab:
        n = st.radio(
            "N-gram size",
            [2, 3, 4],
            horizontal=True,
            format_func=lambda value: f"{value}-grams",
            key="ngram_size",
        )
        ngrams = cached_ngrams(full_text, n, 50)
        if ngrams:
            st.dataframe(
                pd.DataFrame(
                    ngrams,
                    columns=["N-gram", "Frequency"],
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No n-gram results were returned.")

    with kwic_tab:
        query = st.text_input(
            "Search term",
            placeholder="e.g. ইছামতী",
            key="kwic_query",
        )
        if query.strip():
            results = text_analysis.get_kwic(full_text, query.strip())
            if results:
                frame = pd.DataFrame(results)
                visible = [
                    column for column in ["left", "match", "right"]
                    if column in frame.columns
                ]
                st.dataframe(
                    frame[visible],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No matching contexts found.")


# ---------------------------------------------------------------------
# ENTITY CATALOGUE
# ---------------------------------------------------------------------

def page_entities() -> None:
    components.page_header(
        "Entity Catalogue",
        "Manage canonical entities and inspect document-specific mentions.",
    )

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

    category_options = {
        category["name"]: category["category_id"]
        for category in categories
    }

    view_tab, add_tab, edit_tab, document_tab = st.tabs(
        ["Catalogue", "Add Seed Entity", "Edit Entity", "By Document"]
    )

    with view_tab:
        if not entities:
            st.info("No entities have been registered.")
        else:
            frame = pd.DataFrame(rows_as_dicts(entities))
            col_search, col_category = st.columns([2, 1])
            search = col_search.text_input(
                "Search entity name or alias",
                key="entity_search",
            )
            category_filter = col_category.selectbox(
                "Category",
                ["All"] + list(category_options.keys()),
                key="entity_category_filter",
            )

            if search:
                pattern = search.strip()
                frame = frame[
                    frame["canonical_name"].fillna("").str.contains(
                        pattern, case=False, regex=False
                    )
                    | frame["alt_names"].fillna("").str.contains(
                        pattern, case=False, regex=False
                    )
                ]

            if category_filter != "All":
                frame = frame[
                    frame["category_name"] == category_filter
                ]

            visible_columns = [
                c for c in [
                    "entity_id",
                    "canonical_name",
                    "alt_names",
                    "category_name",
                    "mention_count",
                ]
                if c in frame.columns
            ]
            st.dataframe(
                frame[visible_columns],
                hide_index=True,
                width="stretch",
            )

    with add_tab:
        with st.form("add_seed_entity_form"):
            canonical_name = st.text_input("Canonical name *")
            category_name = st.selectbox(
                "Category",
                list(category_options.keys()),
            )
            aliases = st.text_input(
                "Alternative names",
                help="Separate aliases with commas.",
            )
            description = st.text_area("Description")
            submitted = st.form_submit_button(
                "Register Entity",
                type="primary",
            )

        if submitted:
            if not canonical_name.strip():
                st.error("Canonical name is required.")
            else:
                try:
                    with db.get_connection() as conn:
                        entity_id = db.next_entity_id(conn)
                        conn.execute(
                            """
                            INSERT INTO entities
                            (entity_id, profile_id, canonical_name,
                             category_id, alt_names, description, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                entity_id,
                                profile_id,
                                canonical_name.strip(),
                                category_options[category_name],
                                aliases.strip() or None,
                                description.strip() or None,
                                db.utc_now(),
                            ),
                        )
                    st.success(
                        f"Registered {canonical_name.strip()} as {entity_id}."
                    )
                    safe_rerun()
                except Exception as exc:
                    st.error(f"Could not register entity: {exc}")

    with edit_tab:
        if not entities:
            st.info("There are no entities to edit.")
        else:
            entity_map = {
                f"{e['entity_id']} — {e['canonical_name']}": dict(e)
                for e in entities
            }
            selected = st.selectbox(
                "Select entity",
                list(entity_map.keys()),
                key="edit_entity_selection",
            )
            entity = entity_map[selected]

            with st.form("edit_entity_details_form"):
                new_name = st.text_input(
                    "Canonical name",
                    value=entity["canonical_name"] or "",
                )
                category_names = list(category_options.keys())
                current_category = entity["category_name"]
                category_index = (
                    category_names.index(current_category)
                    if current_category in category_names
                    else 0
                )
                new_category = st.selectbox(
                    "Category",
                    category_names,
                    index=category_index,
                )
                new_aliases = st.text_input(
                    "Alternative names",
                    value=entity["alt_names"] or "",
                )
                new_description = st.text_area(
                    "Description",
                    value=entity["description"] or "",
                )
                save = st.form_submit_button(
                    "Save Entity Changes",
                    type="primary",
                )

            if save:
                if not new_name.strip():
                    st.error("Canonical name cannot be empty.")
                else:
                    with db.get_connection() as conn:
                        db.update_entity_details(
                            conn,
                            entity["entity_id"],
                            new_name.strip(),
                            category_options[new_category],
                            new_aliases.strip() or None,
                            new_description.strip() or None,
                        )
                    st.success("Entity updated.")
                    safe_rerun()

            st.warning(
                "Moving an entity to Trash hides it from active catalogues. "
                "Existing mentions remain stored."
            )
            if st.button(
                "Move Entity to Trash",
                key=f"trash_entity_{entity['entity_id']}",
            ):
                with db.get_connection() as conn:
                    db.soft_delete_entity(conn, entity["entity_id"])
                safe_rerun()

            st.subheader("Mentions of this entity")
            with db.get_connection() as conn:
                mentions = db.get_mentions_for_entity(
                    conn,
                    entity["entity_id"],
                )
            if mentions:
                for mention in mentions:
                    with st.container(border=True):
                        st.markdown(
                            f"**{mention['mention_id']}** · "
                            f"`{mention['surface_form']}`"
                        )
                        st.caption(
                            f"Passage: {mention['passage_id']}"
                        )
                        st.write(mention["plain_text"])
                        if st.button(
                            "Move mention to Trash",
                            key=f"trash_mention_{mention['mention_id']}",
                        ):
                            with db.get_connection() as conn:
                                db.delete_mention(
                                    conn,
                                    mention["mention_id"],
                                )
                            safe_rerun()
            else:
                st.info("No active mentions are linked to this entity.")

    with document_tab:
        if not documents:
            st.info("Import documents to inspect document-specific entities.")
        else:
            doc_options = make_document_options(documents)
            selected_doc = st.selectbox(
                "Document",
                list(doc_options.keys()),
                key="entity_document_scope",
            )
            doc_id = doc_options[selected_doc]

            with db.get_connection() as conn:
                document_entities = scoped_entity_rows(
                    conn,
                    profile_id,
                    doc_id,
                )
                mention_rows = conn.execute(
                    """
                    SELECT
                        m.mention_id,
                        m.entity_id,
                        e.canonical_name,
                        m.surface_form,
                        m.passage_id,
                        m.char_start,
                        m.char_end,
                        m.status,
                        m.note
                    FROM mentions m
                    JOIN entities e ON e.entity_id = m.entity_id
                    WHERE m.doc_id = ?
                      AND m.deleted_at IS NULL
                    ORDER BY m.passage_id, m.char_start
                    """,
                    (doc_id,),
                ).fetchall()

            st.subheader("Entities mentioned in this document")
            present = [
                dict(row) for row in document_entities
                if row["mention_count"] > 0
            ]
            if present:
                st.dataframe(
                    pd.DataFrame(present),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No entity mentions have been annotated in this document.")

            st.subheader("Document mention register")
            if mention_rows:
                st.dataframe(
                    pd.DataFrame(rows_as_dicts(mention_rows)),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No mentions are registered for this document.")


# ---------------------------------------------------------------------
# RELATIONSHIP MANAGEMENT
# ---------------------------------------------------------------------

def page_relationships() -> None:
    components.page_header(
        "Relationship Management",
        "Record researcher-defined relations and their supporting evidence.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)

    if not profiles:
        render_empty("Create a taxonomy profile first.")
        return
    if not documents:
        render_empty("Import documents before creating document-scoped relations.")
        return

    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        entities = db.get_entities(conn, profile_id)
        relationship_types = db.get_relationship_types(conn, profile_id)

    if len(entities) < 2:
        render_empty("Register at least two entities before creating relations.")
        return
    if not relationship_types:
        render_empty("Add relationship types in Taxonomy Manager first.")
        return

    doc_options = make_document_options(documents)
    selected_doc_label = st.selectbox(
        "Research document",
        list(doc_options.keys()),
        key="relationship_document_scope",
    )
    doc_id = doc_options[selected_doc_label]

    with db.get_connection() as conn:
        relationships = scoped_relationship_rows(conn, doc_id)

    entity_options = {
        f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"]
        for e in entities
    }
    type_options = {
        rt["name"]: rt["type_id"]
        for rt in relationship_types
    }

    view_tab, add_tab = st.tabs(
        ["Document Relationships", "Add Relationship"]
    )

    with view_tab:
        if not relationships:
            st.info("No relationships are registered for this document.")
        else:
            for relation in relationships:
                with st.container(border=True):
                    st.markdown(
                        f"**{relation['source_name']}** "
                        f"`[{relation['type_name']}]` "
                        f"**{relation['target_name']}**"
                    )
                    if relation["description"]:
                        st.write(relation["description"])
                    st.caption(
                        f"Relationship ID: {relation['relationship_id']} "
                        f"· Document: {relation['doc_id'] or 'Unscoped legacy record'}"
                    )

                    with st.expander("Edit relationship and evidence"):
                        current_source = next(
                            (
                                label for label, value in entity_options.items()
                                if value == relation["source_entity_id"]
                            ),
                            None,
                        )
                        current_target = next(
                            (
                                label for label, value in entity_options.items()
                                if value == relation["target_entity_id"]
                            ),
                            None,
                        )

                        with st.form(
                            f"edit_relationship_{relation['relationship_id']}"
                        ):
                            source_label = st.selectbox(
                                "Source entity",
                                list(entity_options.keys()),
                                index=(
                                    list(entity_options.keys()).index(current_source)
                                    if current_source else 0
                                ),
                            )
                            target_label = st.selectbox(
                                "Target entity",
                                list(entity_options.keys()),
                                index=(
                                    list(entity_options.keys()).index(current_target)
                                    if current_target else 0
                                ),
                            )
                            type_names = list(type_options.keys())
                            current_type_index = (
                                type_names.index(relation["type_name"])
                                if relation["type_name"] in type_names
                                else 0
                            )
                            relation_type = st.selectbox(
                                "Relationship type",
                                type_names,
                                index=current_type_index,
                            )
                            description = st.text_area(
                                "Description / interpretation",
                                value=relation["description"] or "",
                            )
                            save_relation = st.form_submit_button(
                                "Update Relationship",
                                type="primary",
                            )

                        if save_relation:
                            if source_label == target_label:
                                st.error(
                                    "Source and target must be different."
                                )
                            else:
                                with db.get_connection() as conn:
                                    db.update_relationship(
                                        conn,
                                        relation["relationship_id"],
                                        entity_options[source_label],
                                        entity_options[target_label],
                                        type_options[relation_type],
                                        description.strip(),
                                    )
                                safe_rerun()

                        with db.get_connection() as conn:
                            evidence = db.get_evidence_for_relationship(
                                conn,
                                relation["relationship_id"],
                            )

                        st.markdown("**Evidence bundles**")
                        if evidence:
                            for item in evidence:
                                with st.container(border=True):
                                    st.markdown(
                                        f"**{item['evidence_domain']}**"
                                    )
                                    st.write(item["source_text"])
                                    if item["context"]:
                                        st.caption(item["context"])
                                    if st.button(
                                        "Delete evidence",
                                        key=f"delete_evidence_{item['evidence_id']}",
                                    ):
                                        with db.get_connection() as conn:
                                            db.delete_evidence_bundle(
                                                conn,
                                                item["evidence_id"],
                                            )
                                        safe_rerun()
                        else:
                            st.info("No evidence bundles have been attached.")

                        with st.form(
                            f"add_evidence_{relation['relationship_id']}"
                        ):
                            domain = st.selectbox(
                                "Evidence domain",
                                ["Literary", "Historical", "Geographical"],
                            )
                            source_text = st.text_area(
                                "Evidence passage / source text *"
                            )
                            context = st.text_input(
                                "Reference or context"
                            )
                            add_evidence = st.form_submit_button(
                                "Attach Evidence",
                            )

                        if add_evidence:
                            if not source_text.strip():
                                st.error("Evidence text is required.")
                            else:
                                with db.get_connection() as conn:
                                    db.add_evidence_bundle(
                                        conn,
                                        relation["relationship_id"],
                                        domain,
                                        source_text.strip(),
                                        context.strip(),
                                    )
                                safe_rerun()

                    if st.button(
                        "Move Relationship to Trash",
                        key=f"trash_relationship_{relation['relationship_id']}",
                    ):
                        with db.get_connection() as conn:
                            conn.execute(
                                """
                                UPDATE relationships
                                SET deleted_at = ?
                                WHERE relationship_id = ?
                                """,
                                (
                                    db.utc_now(),
                                    relation["relationship_id"],
                                ),
                            )
                        safe_rerun()

    with add_tab:
        with st.form("add_document_relationship_form"):
            source = st.selectbox(
                "Source entity",
                list(entity_options.keys()),
            )
            target = st.selectbox(
                "Target entity",
                list(entity_options.keys()),
            )
            relation_type = st.selectbox(
                "Relationship type",
                list(type_options.keys()),
            )
            description = st.text_area(
                "Description / interpretation",
                help="Describe the relationship as a research claim, not as an automatic fact.",
            )
            confidence = st.selectbox(
                "Research assessment",
                ["Unassessed", "Tentative", "Moderate", "Strong", "Contested"],
            )
            submitted = st.form_submit_button(
                "Save Document Relationship",
                type="primary",
            )

        if submitted:
            if source == target:
                st.error("Source and target must be different.")
            else:
                try:
                    with db.get_connection() as conn:
                        # The existing db.save_relationship helper does not
                        # accept doc_id. Save through it, then scope the new
                        # record in the same database transaction.
                        db.save_relationship(
                            conn,
                            entity_options[source],
                            entity_options[target],
                            type_options[relation_type],
                            description.strip(),
                        )
                        latest = conn.execute(
                            """
                            SELECT relationship_id
                            FROM relationships
                            WHERE source_entity_id = ?
                              AND target_entity_id = ?
                              AND type_id = ?
                            ORDER BY created_at DESC
                            LIMIT 1
                            """,
                            (
                                entity_options[source],
                                entity_options[target],
                                type_options[relation_type],
                            ),
                        ).fetchone()
                        if latest:
                            conn.execute(
                                """
                                UPDATE relationships
                                SET doc_id = ?, confidence = ?
                                WHERE relationship_id = ?
                                """,
                                (
                                    doc_id,
                                    confidence,
                                    latest["relationship_id"],
                                ),
                            )
                    st.success("Document-scoped relationship saved.")
                    safe_rerun()
                except Exception as exc:
                    st.error(f"Could not save relationship: {exc}")


# ---------------------------------------------------------------------
# AI CANDIDATE REVIEW
# ---------------------------------------------------------------------

def page_ai_review() -> None:
    components.page_header(
        "AI Candidate Review",
        "Review machine-generated entity candidates. Researcher decisions remain authoritative.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)

    if not documents:
        render_empty("Import a document before running candidate recognition.")
        return
    if not profiles:
        render_empty("Create a taxonomy profile first.")
        return

    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        existing_entities = db.get_entities(conn, profile_id)

    if not categories:
        render_empty("The taxonomy profile has no entity categories.")
        return

    doc_options = make_document_options(documents)
    selected_doc_label = st.selectbox(
        "Document",
        list(doc_options.keys()),
        key="ai_review_document",
    )
    doc_id = doc_options[selected_doc_label]

    category_map = {
        category["name"].lower(): category["category_id"]
        for category in categories
    }

    if st.button(
        "Run Entity Candidate Recognition",
        type="primary",
        key="run_entity_recognition",
    ):
        progress = st.progress(0.0, text="Preparing document...")
        try:
            with db.get_connection() as conn:
                passages = db.get_passages(conn, doc_id)

            def update_progress(current: int, total: int) -> None:
                fraction = current / total if total else 1.0
                progress.progress(
                    fraction,
                    text=f"Scanning passage {current} of {total}",
                )

            candidates = ai_recognizer.recognize_candidates(
                passages,
                category_map,
                existing_entities,
                progress_callback=update_progress,
            )
            with db.get_connection() as conn:
                saved_count = db.bulk_save_candidates(conn, candidates)

            progress.empty()
            st.success(
                f"{saved_count} new candidate(s) saved for review."
            )
            safe_rerun()
        except Exception as exc:
            progress.empty()
            st.error(f"Candidate recognition failed: {exc}")

    st.divider()

    with db.get_connection() as conn:
        total = db.count_candidates(conn, doc_id)
        candidates = db.get_candidates_paginated(
            conn,
            doc_id,
            20,
            0,
        )
        entities = db.get_entities(conn, profile_id)

    st.subheader(f"Pending candidates: {total}")

    if not candidates:
        st.info("No pending candidates for this document.")
        return

    category_options = {
        category["name"]: category["category_id"]
        for category in categories
    }
    existing_entity_options = {
        f"{entity['entity_id']} — {entity['canonical_name']}":
            entity["entity_id"]
        for entity in entities
    }

    for candidate in candidates:
        with st.container(border=True):
            st.markdown(
                f"### Candidate: `{candidate['surface_form']}`"
            )
            passage_text = candidate["passage_text"] or ""
            start = int(candidate["char_start"])
            end = int(candidate["char_end"])
            left = max(0, start - 70)
            right = min(len(passage_text), end + 70)
            context = passage_text[left:right]
            st.code(context, language=None)

            st.caption(
                f"Method: {candidate['recognition_method'] or 'Unspecified'} "
                f"· Confidence score: {candidate['confidence_score']}"
            )
            if candidate["contextual_evidence"]:
                st.write(candidate["contextual_evidence"])

            suggested = candidate["suggested_category_name"]
            category_names = list(category_options.keys())
            default_category_index = (
                category_names.index(suggested)
                if suggested in category_names
                else 0
            )

            category_name = st.selectbox(
                "Verified category",
                category_names,
                index=default_category_index,
                key=f"candidate_category_{candidate['candidate_id']}",
            )

            resolution = st.radio(
                "Researcher decision",
                [
                    "Link to existing entity",
                    "Create new entity",
                    "Reject candidate",
                    "Defer decision",
                ],
                key=f"candidate_resolution_{candidate['candidate_id']}",
            )

            selected_existing = None
            new_canonical_name = candidate["surface_form"]
            if resolution == "Link to existing entity":
                if existing_entity_options:
                    selected_existing = st.selectbox(
                        "Existing entity",
                        list(existing_entity_options.keys()),
                        key=f"candidate_entity_{candidate['candidate_id']}",
                    )
                else:
                    st.warning("No existing entities are available.")

            if resolution == "Create new entity":
                new_canonical_name = st.text_input(
                    "Canonical entity name",
                    value=candidate["surface_form"],
                    key=f"candidate_new_name_{candidate['candidate_id']}",
                )

            col_accept, col_reject = st.columns(2)
            with col_accept:
                if st.button(
                    "Apply Decision",
                    key=f"apply_candidate_{candidate['candidate_id']}",
                    type="primary",
                ):
                    try:
                        if resolution == "Defer decision":
                            st.info("Candidate left pending for later review.")
                        elif resolution == "Reject candidate":
                            with db.get_connection() as conn:
                                db.update_candidate_status(
                                    conn,
                                    candidate["candidate_id"],
                                    "rejected",
                                )
                            safe_rerun()
                        else:
                            with db.get_connection() as conn:
                                if resolution == "Link to existing entity":
                                    if not selected_existing:
                                        st.error(
                                            "Select an existing entity first."
                                        )
                                        continue
                                    entity_id = existing_entity_options[
                                        selected_existing
                                    ]
                                else:
                                    if not new_canonical_name.strip():
                                        st.error(
                                            "Canonical entity name is required."
                                        )
                                        continue
                                    entity_id = db.next_entity_id(conn)
                                    conn.execute(
                                        """
                                        INSERT INTO entities
                                        (entity_id, profile_id, canonical_name,
                                         category_id, created_at)
                                        VALUES (?, ?, ?, ?, ?)
                                        """,
                                        (
                                            entity_id,
                                            profile_id,
                                            new_canonical_name.strip(),
                                            category_options[category_name],
                                            db.utc_now(),
                                        ),
                                    )

                                db.save_mention(
                                    conn,
                                    entity_id=entity_id,
                                    doc_id=doc_id,
                                    passage_id=candidate["passage_id"],
                                    surface_form=candidate["surface_form"],
                                    char_start=candidate["char_start"],
                                    char_end=candidate["char_end"],
                                )
                                db.update_candidate_status(
                                    conn,
                                    candidate["candidate_id"],
                                    "accepted",
                                )
                            safe_rerun()
                    except Exception as exc:
                        st.error(f"Could not apply decision: {exc}")

            with col_reject:
                if st.button(
                    "Reject",
                    key=f"reject_candidate_{candidate['candidate_id']}",
                ):
                    with db.get_connection() as conn:
                        db.update_candidate_status(
                            conn,
                            candidate["candidate_id"],
                            "rejected",
                        )
                    safe_rerun()


# ---------------------------------------------------------------------
# TRASH AND RECOVERY
# ---------------------------------------------------------------------

def page_trash() -> None:
    components.page_header(
        "Trash & Recovery",
        "Restore soft-deleted documents and entities.",
    )

    with db.get_connection() as conn:
        all_documents = db.list_documents(
            conn,
            include_deleted=True,
        )
        deleted_documents = [
            document for document in all_documents
            if document["deleted_at"] is not None
        ]
        deleted_entities = conn.execute(
            """
            SELECT entity_id, canonical_name, deleted_at
            FROM entities
            WHERE deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
            """
        ).fetchall()

    if not deleted_documents and not deleted_entities:
        render_empty("Trash is empty.")
        return

    if deleted_documents:
        st.subheader("Deleted Documents")
        for document in deleted_documents:
            with st.container(border=True):
                col_info, col_restore = st.columns([4, 1])
                col_info.markdown(
                    f"**{document['doc_id']}** — {document['title']}"
                )
                col_info.caption(
                    f"Deleted: {document['deleted_at']}"
                )
                if col_restore.button(
                    "Restore",
                    key=f"restore_document_{document['doc_id']}",
                    type="primary",
                    width="stretch",
                ):
                    with db.get_connection() as conn:
                        db.restore_document(conn, document["doc_id"])
                    safe_rerun()

    if deleted_entities:
        st.subheader("Deleted Entities")
        for entity in deleted_entities:
            with st.container(border=True):
                col_info, col_restore = st.columns([4, 1])
                col_info.markdown(
                    f"**{entity['entity_id']}** — "
                    f"{entity['canonical_name']}"
                )
                col_info.caption(
                    f"Deleted: {entity['deleted_at']}"
                )
                if col_restore.button(
                    "Restore",
                    key=f"restore_entity_{entity['entity_id']}",
                    type="primary",
                    width="stretch",
                ):
                    with db.get_connection() as conn:
                        db.restore_entity(conn, entity["entity_id"])
                    safe_rerun()

    st.info(
        "Permanent deletion is intentionally not exposed in this version. "
        "The database contains linked annotations, evidence and research "
        "records that must be checked before irreversible deletion."
    )


# ---------------------------------------------------------------------
# EXPORT CENTRE
# ---------------------------------------------------------------------

def page_export() -> None:
    components.page_header(
        "Export Centre",
        "Export structured data for external research tools.",
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if not documents:
        render_empty("Import documents before exporting research data.")
        return

    json_tab, tei_tab, network_tab, spatial_tab = st.tabs(
        ["Dataset JSON", "TEI XML", "Network", "Spatial"]
    )

    with json_tab:
        st.subheader("Complete dataset")
        try:
            with db.get_connection() as conn:
                json_data = exporter.generate_json_export(conn)
            st.download_button(
                "Download JSON",
                data=json_data.encode("utf-8"),
                file_name="textencode_dataset.json",
                mime="application/json",
                type="primary",
            )
        except Exception as exc:
            st.error(f"JSON export failed: {exc}")

    with tei_tab:
        st.warning(
            "The current exporter produces TEI-oriented XML. Validate the "
            "result against your chosen TEI P5 schema/ODD before treating "
            "it as validated TEI."
        )
        document_options = make_document_options(documents)
        selected = st.selectbox(
            "Document to export",
            list(document_options.keys()),
            key="tei_document",
        )
        if st.button("Generate TEI XML", type="primary"):
            try:
                with db.get_connection() as conn:
                    xml_data = exporter.generate_tei_xml(
                        conn,
                        document_options[selected],
                    )
                st.download_button(
                    "Download TEI XML",
                    data=xml_data.encode("utf-8"),
                    file_name=f"{document_options[selected]}_tei.xml",
                    mime="application/xml",
                )
            except Exception as exc:
                st.error(f"TEI export failed: {exc}")

    with network_tab:
        st.subheader("Gephi-compatible network files")
        scope_options: dict[str, str | None] = {
            "All documents / global": None
        }
        scope_options.update(
            {
                f"Document: {label}": doc_id
                for label, doc_id in make_document_options(documents).items()
            }
        )
        scope = st.selectbox(
            "Network scope",
            list(scope_options.keys()),
            key="network_export_scope",
        )
        if st.button("Generate network exports", type="primary"):
            try:
                with db.get_connection() as conn:
                    graph_data, nodes_csv, edges_csv = (
                        exporter.generate_gephi_data(
                            conn,
                            scope_options[scope],
                        )
                    )
                col1, col2, col3 = st.columns(3)
                col1.download_button(
                    "Download GEXF",
                    data=graph_data,
                    file_name="textencode_network.gexf",
                    mime="application/gexf+xml",
                    width="stretch",
                )
                col2.download_button(
                    "Download Nodes CSV",
                    data=nodes_csv,
                    file_name="textencode_nodes.csv",
                    mime="text/csv",
                    width="stretch",
                )
                col3.download_button(
                    "Download Edges CSV",
                    data=edges_csv,
                    file_name="textencode_edges.csv",
                    mime="text/csv",
                    width="stretch",
                )
            except Exception as exc:
                st.error(f"Network export failed: {exc}")

    with spatial_tab:
        st.subheader("GeoJSON for QGIS")
        if st.button("Generate GeoJSON", type="primary"):
            try:
                with db.get_connection() as conn:
                    geojson_data = exporter.generate_qgis_geojson(conn)
                st.download_button(
                    "Download GeoJSON",
                    data=geojson_data.encode("utf-8"),
                    file_name="textencode_spatial_data.geojson",
                    mime="application/geo+json",
                )
            except Exception as exc:
                st.error(f"Spatial export failed: {exc}")




# ---------------------------------------------------------------------
# v0.6.1 COMPATIBILITY AND SCOPED ANALYSIS OVERRIDES
# These functions intentionally use the actual v0.5 SQLite schema.
# ---------------------------------------------------------------------

def _project_document_scope(key_prefix: str):
    """Return active documents filtered by project/corpus/document scope."""
    with db.get_connection() as conn:
        projects = db.get_projects(conn)
        all_documents = db.list_documents(conn)

    if not all_documents:
        st.info("No active documents are available.")
        return [], None

    scope_labels = ["All active documents", "One project", "One corpus", "One document"]
    scope = st.selectbox("Analysis scope", scope_labels, key=f"{key_prefix}_scope")
    if scope == "All active documents":
        return all_documents, None

    if scope == "One project":
        if not projects:
            return [], None
        project_options = {
            f"{p['name']} (Project {p['project_id']})": p["project_id"]
            for p in projects
        }
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
                    corpus_options[
                        f"{project['name']} / {corpus['name']} (#{corpus['corpus_id']})"
                    ] = corpus["corpus_id"]
        if not corpus_options:
            return [], None
        selected = st.selectbox("Corpus", list(corpus_options), key=f"{key_prefix}_corpus")
        corpus_id = corpus_options[selected]
        return [d for d in all_documents if d["corpus_id"] == corpus_id], corpus_id

    options = make_document_options(all_documents)
    selected = st.selectbox("Document", list(options), key=f"{key_prefix}_document")
    doc_id = options[selected]
    return [d for d in all_documents if d["doc_id"] == doc_id], doc_id


def page_text_analysis() -> None:
    components.page_header(
        "Text Analysis",
        "Analyse one document, a corpus, a project or all active documents.",
    )
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
    stats_tab, freq_tab, ngram_tab, kwic_tab = st.tabs(
        ["Overview", "Word Frequency", "N-Grams", "Concordance (KWIC)"]
    )
    with stats_tab:
        stats = cached_stats(full_text)
        components.metric_row([
            {"label": str(k).replace("_", " ").title(), "value": v}
            for k, v in stats.items()
        ])
    with freq_tab:
        limit = st.slider("Top terms", 10, 200, 50, 10, key="scoped_freq_limit")
        values = cached_frequency(full_text, limit)
        if values:
            st.dataframe(pd.DataFrame(values, columns=["Term", "Frequency"]),
                         hide_index=True, width="stretch")
        else:
            st.info("No frequency results.")
    with ngram_tab:
        n = st.radio("N-gram size", [2, 3, 4], horizontal=True, key="scoped_ngram_size")
        values = cached_ngrams(full_text, n, 50)
        if values:
            st.dataframe(pd.DataFrame(values, columns=["N-gram", "Frequency"]),
                         hide_index=True, width="stretch")
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


def page_network_analysis() -> None:
    components.page_header(
        "Network Analysis",
        "Explore researcher-defined entity relationships by document, corpus, project or across the active collection.",
    )
    scoped_docs, _ = _project_document_scope("network")
    if not scoped_docs:
        st.info("No documents in this scope.")
        return
    doc_ids = [d["doc_id"] for d in scoped_docs]
    placeholders = ",".join("?" for _ in doc_ids)
    with db.get_connection() as conn:
        relations = conn.execute(
            f"""
            SELECT r.relationship_id, r.source_entity_id, r.target_entity_id,
                   s.canonical_name AS source_name, t.canonical_name AS target_name,
                   rt.name AS type_name, r.description, r.doc_id
            FROM relationships r
            JOIN entities s ON s.entity_id = r.source_entity_id
            JOIN entities t ON t.entity_id = r.target_entity_id
            JOIN relationship_types rt ON rt.type_id = r.type_id
            WHERE r.deleted_at IS NULL
              AND (r.doc_id IN ({placeholders}) OR r.doc_id IS NULL)
            ORDER BY r.created_at
            """,
            doc_ids,
        ).fetchall()

    if not relations:
        st.info("No relationships found in this scope. Create them in Relationships.")
        return

    from streamlit_agraph import agraph, Node, Edge, Config
    nodes = {}
    edges = []
    for relation in relations:
        source_id = relation["source_entity_id"]
        target_id = relation["target_entity_id"]
        nodes.setdefault(
            source_id,
            Node(id=source_id, label=relation["source_name"], size=22, color="#244C56"),
        )
        nodes.setdefault(
            target_id,
            Node(id=target_id, label=relation["target_name"], size=22, color="#A7895B"),
        )
        edges.append(
            Edge(
                source=source_id,
                target=target_id,
                label=relation["type_name"],
                color="#E5E2DB",
            )
        )
    st.caption(
        f"{len(scoped_docs)} document(s) · {len(nodes)} entities · "
        f"{len(edges)} relationship records"
    )
    agraph(
        nodes=list(nodes.values()),
        edges=edges,
        config=Config(
            width="100%", height=650, directed=True, physics=True,
            hierarchical=False, nodeHighlightBehavior=True,
            highlightColor="#F7A7A6", collapsible=False,
        ),
    )
    with st.expander("Relationship data"):
        st.dataframe(pd.DataFrame(rows_as_dicts(relations)),
                     hide_index=True, width="stretch")


def page_spatial_analysis() -> None:
    components.page_header(
        "Spatial Analysis",
        "Map georeferenced entities within a document, corpus, project or the active collection.",
    )
    scoped_docs, _ = _project_document_scope("spatial")
    if not scoped_docs:
        st.info("No documents in this scope.")
        return
    doc_ids = [d["doc_id"] for d in scoped_docs]
    placeholders = ",".join("?" for _ in doc_ids)
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        if not profiles:
            st.warning("Create a taxonomy profile first.")
            return
        profile_id = profiles[0]["profile_id"]
        entities = conn.execute(
            f"""
            SELECT DISTINCT e.entity_id, e.canonical_name, e.latitude,
                   e.longitude, c.name AS category_name, e.doc_id
            FROM entities e
            JOIN entity_categories c ON c.category_id = e.category_id
            LEFT JOIN mentions m ON m.entity_id = e.entity_id
            WHERE e.profile_id = ? AND e.deleted_at IS NULL
              AND (e.doc_id IN ({placeholders}) OR m.doc_id IN ({placeholders}))
            ORDER BY e.canonical_name
            """,
            [profile_id] + doc_ids + doc_ids,
        ).fetchall()

    mapped = [
        dict(e) for e in entities
        if e["latitude"] is not None and e["longitude"] is not None
    ]
    if mapped:
        frame = pd.DataFrame([
            {
                "name": e["canonical_name"],
                "lat": e["latitude"],
                "lon": e["longitude"],
                "category": e["category_name"],
            }
            for e in mapped
        ])
        st.caption(f"{len(frame)} mapped entities from {len(scoped_docs)} document(s).")
        st.map(frame, latitude="lat", longitude="lon")
        st.dataframe(frame, hide_index=True, width="stretch")
    else:
        st.info("No georeferenced entities occur in this scope.")

    with st.expander("Add or edit entity coordinates"):
        all_entities = [dict(e) for e in entities]
        if not all_entities:
            st.info("No entities are associated with this scope.")
        else:
            entity_options = {
                f"{e['entity_id']} — {e['canonical_name']}": e
                for e in all_entities
            }
            selected = st.selectbox("Entity", list(entity_options), key="spatial_entity")
            entity = entity_options[selected]
            with st.form("spatial_coordinate_form"):
                lat = st.number_input(
                    "Latitude",
                    value=float(entity["latitude"] or 0.0),
                    min_value=-90.0,
                    max_value=90.0,
                    format="%.6f",
                )
                lon = st.number_input(
                    "Longitude",
                    value=float(entity["longitude"] or 0.0),
                    min_value=-180.0,
                    max_value=180.0,
                    format="%.6f",
                )
                save = st.form_submit_button("Save coordinates", type="primary")
                clear = st.form_submit_button("Clear coordinates")
            if save:
                with db.get_connection() as conn:
                    conn.execute(
                        "UPDATE entities SET latitude=?, longitude=? WHERE entity_id=?",
                        (lat, lon, entity["entity_id"]),
                    )
                st.success("Coordinates saved.")
                st.rerun()
            if clear:
                with db.get_connection() as conn:
                    conn.execute(
                        "UPDATE entities SET latitude=NULL, longitude=NULL WHERE entity_id=?",
                        (entity["entity_id"],),
                    )
                st.success("Coordinates cleared.")
                st.rerun()


def page_taxonomy_manager() -> None:
    """Taxonomy UI compatible with the actual v0.5 db.py API.

    The previous taxonomy module called db.export_profile/import_profile,
    neither of which exists in the repository's database layer.
    """
    import json

    components.page_header(
        "Taxonomy Manager",
        "Manage entity categories, relationship types and metadata fields.",
    )
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
    if not profiles:
        st.error("No taxonomy profile found.")
        return
    profile_options = {p["name"]: p["profile_id"] for p in profiles}
    selected_profile = st.selectbox("Active profile", list(profile_options), key="taxonomy_profile")
    profile_id = profile_options[selected_profile]

    cat_tab, rel_tab, attr_tab, export_tab = st.tabs(
        ["Entity Categories", "Relationship Types", "Custom Metadata", "Export"]
    )
    with cat_tab:
        with db.get_connection() as conn:
            categories = db.get_categories(conn, profile_id)
        category_map = {c["name"]: c["category_id"] for c in categories}
        with st.form("taxonomy_add_category"):
            name = st.text_input("Category name")
            description = st.text_input("Description")
            parent_name = st.selectbox("Parent category (optional)", ["None"] + list(category_map))
            add = st.form_submit_button("Add category", type="primary")
        if add:
            if not name.strip():
                st.error("Category name is required.")
            else:
                with db.get_connection() as conn:
                    db.save_category(
                        conn, profile_id=profile_id, name=name.strip(),
                        description=description.strip(),
                        parent_id=category_map.get(parent_name),
                    )
                st.success("Category added.")
                st.rerun()
        if categories:
            st.dataframe(pd.DataFrame(rows_as_dicts(categories)),
                         hide_index=True, width="stretch")

    with rel_tab:
        with db.get_connection() as conn:
            relation_types = db.get_relationship_types(conn, profile_id)
        with st.form("taxonomy_add_relation_type"):
            name = st.text_input("Relationship type name")
            group = st.text_input("Group", value="General")
            description = st.text_input("Description")
            directed = st.checkbox("Directed relationship", value=True)
            add = st.form_submit_button("Add relationship type", type="primary")
        if add:
            if not name.strip():
                st.error("Relationship type name is required.")
            else:
                with db.get_connection() as conn:
                    db.save_relationship_type(
                        conn, profile_id=profile_id, group_name=group.strip(),
                        name=name.strip(), description=description.strip(),
                        directed=1 if directed else 0,
                    )
                st.success("Relationship type added.")
                st.rerun()
        if relation_types:
            st.dataframe(pd.DataFrame(rows_as_dicts(relation_types)),
                         hide_index=True, width="stretch")

    with attr_tab:
        with db.get_connection() as conn:
            attributes = db.get_attribute_definitions(conn, profile_id)
        with st.form("taxonomy_add_attribute"):
            target = st.selectbox("Applies to", ["entities", "relationships"])
            name = st.text_input("Attribute name")
            data_type = st.selectbox(
                "Data type", ["text", "integer", "decimal", "date", "boolean", "json"]
            )
            add = st.form_submit_button("Add metadata field", type="primary")
        if add:
            if not name.strip():
                st.error("Attribute name is required.")
            else:
                with db.get_connection() as conn:
                    db.save_attribute_definition(
                        conn, profile_id=profile_id, target_table=target,
                        category_id=None, name=name.strip(),
                        data_type=data_type, description="",
                    )
                st.success("Metadata field added.")
                st.rerun()
        if attributes:
            st.dataframe(pd.DataFrame(rows_as_dicts(attributes)),
                         hide_index=True, width="stretch")

    with export_tab:
        # Build a portable JSON export directly from tables. No missing db helper.
        with db.get_connection() as conn:
            profile = dict(conn.execute(
                "SELECT * FROM taxonomy_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone())
            categories = rows_as_dicts(db.get_categories(conn, profile_id))
            relation_types = rows_as_dicts(db.get_relationship_types(conn, profile_id))
            attributes = rows_as_dicts(db.get_attribute_definitions(conn, profile_id))
        payload = {
            "format": "TextEncodeTaxonomy",
            "version": 1,
            "profile": profile,
            "categories": categories,
            "relationship_types": relation_types,
            "attribute_definitions": attributes,
        }
        st.download_button(
            "Download taxonomy JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"textencode_taxonomy_{profile_id}.json",
            mime="application/json",
        )
        st.caption(
            "Import is not offered here because the current database module "
            "does not implement a safe import_profile operation."
        )


def page_manual_annotation() -> None:
    """Manual workflow supports entity registration and optional linking."""
    components.page_header(
        "Manual Annotation",
        "Register one entity, annotate a passage, and optionally link entities.",
    )
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
    if not documents or not profiles:
        st.info("You need at least one document and one taxonomy profile.")
        return
    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        categories = db.get_categories(conn, profile_id)
        entities = db.get_entities(conn, profile_id)

    register_tab, annotate_tab, link_tab = st.tabs(
        ["Register Single Entity", "Annotate Text", "Link Entities"]
    )
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
                    conn.execute(
                        """INSERT INTO entities
                        (entity_id, profile_id, canonical_name, category_id,
                         alt_names, description, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entity_id, profile_id, name.strip(),
                            cat_options[category], aliases.strip() or None,
                            description.strip() or None, db.utc_now(),
                        ),
                    )
                st.success(f"Registered {name.strip()} ({entity_id}).")
                st.rerun()

    with annotate_tab:
        doc_options = make_document_options(documents)
        doc_label = st.selectbox("Document", list(doc_options), key="manual_doc")
        doc_id = doc_options[doc_label]
        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)
            entities = db.get_entities(conn, profile_id)
        if passages and entities:
            passage_options = {
                f"{p['passage_id']} · {p['plain_text'][:90]}": p
                for p in passages
            }
            passage_label = st.selectbox(
                "Passage", list(passage_options), key="manual_passage"
            )
            passage = passage_options[passage_label]
            passage_text = passage["plain_text"] or ""
            st.text_area("Source passage", passage_text, height=160, disabled=True)
            entity_options = {
                f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"]
                for e in entities
            }
            with st.form("manual_annotate_single_mention"):
                surface = st.text_input("Exact word or phrase")
                entity_label = st.selectbox("Link mention to entity", list(entity_options))
                occurrences = find_all_occurrences(passage_text, surface.strip()) if surface.strip() else []
                occurrence = st.selectbox(
                    "Occurrence",
                    list(range(1, len(occurrences) + 1)) or [1],
                    format_func=lambda x: f"Occurrence {x}",
                )
                note = st.text_area("Research note (optional)")
                save = st.form_submit_button("Save mention", type="primary")
            if save:
                if not occurrences:
                    st.error("That exact word or phrase does not occur in this passage.")
                else:
                    start, end = occurrences[occurrence - 1]
                    with db.get_connection() as conn:
                        db.save_mention(
                            conn, entity_id=entity_options[entity_label],
                            doc_id=doc_id, passage_id=passage["passage_id"],
                            surface_form=surface.strip(), char_start=start,
                            char_end=end, note=note.strip() or None,
                        )
                    st.success("Mention saved.")
                    st.rerun()
        else:
            st.info("This document needs passages and at least one registered entity.")

    with link_tab:
        with db.get_connection() as conn:
            entities = db.get_entities(conn, profile_id)
            rel_types = db.get_relationship_types(conn, profile_id)
        if len(entities) < 2 or not rel_types:
            st.info("Register at least two entities and relationship types to create a link.")
        else:
            entity_options = {
                f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"]
                for e in entities
            }
            type_options = {r["name"]: r["type_id"] for r in rel_types}
            link_mode = st.radio(
                "Entity relationship",
                ["Do not link entities", "Link two entities"],
                horizontal=True,
                key="manual_link_mode",
            )
            if link_mode == "Link two entities":
                with st.form("manual_optional_entity_link"):
                    source = st.selectbox("Source entity", list(entity_options))
                    target = st.selectbox("Target entity", list(entity_options))
                    relation = st.selectbox("Relationship type", list(type_options))
                    description = st.text_area("Description / interpretation")
                    link = st.form_submit_button("Create link", type="primary")
                if link:
                    if source == target:
                        st.error("Choose two different entities.")
                    else:
                        with db.get_connection() as conn:
                            db.save_relationship(
                                conn, entity_options[source], entity_options[target],
                                type_options[relation], description.strip(),
                            )
                        st.success("Relationship created. It is currently global because the legacy schema helper does not take a document argument.")
                        st.rerun()
            else:
                st.info("Entity registration and annotation do not require creating a relationship.")


def page_trash() -> None:
    """Restore and permanently delete selected records with explicit confirmation."""
    components.page_header(
        "Trash & Recovery",
        "Restore deleted records or permanently remove them after confirmation.",
    )
    with db.get_connection() as conn:
        documents = db.list_documents(conn, include_deleted=True)
        deleted_docs = [d for d in documents if d["deleted_at"] is not None]
        deleted_entities = conn.execute(
            "SELECT * FROM entities WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()
    if not deleted_docs and not deleted_entities:
        components.empty_state("Trash is empty.")
        return

    if deleted_docs:
        st.subheader("Deleted Documents")
        for document in deleted_docs:
            with st.container(border=True):
                st.markdown(f"**{document['doc_id']} — {document['title']}**")
                st.caption(f"Deleted: {document['deleted_at']}")
                restore_col, delete_col = st.columns(2)
                if restore_col.button(
                    "Restore document",
                    key=f"restore_doc_{document['doc_id']}",
                    type="primary",
                ):
                    with db.get_connection() as conn:
                        db.restore_document(conn, document["doc_id"])
                    st.rerun()
                confirm = delete_col.checkbox(
                    "I understand this is irreversible",
                    key=f"confirm_delete_doc_{document['doc_id']}",
                )
                if delete_col.button(
                    "Permanently delete",
                    key=f"permanent_doc_{document['doc_id']}",
                    disabled=not confirm,
                ):
                    with db.get_connection() as conn:
                        # Clean dependent non-FK records first, then the
                        # document. DB cascades passages, mentions, candidates.
                        conn.execute(
                            "DELETE FROM relationships WHERE doc_id=?",
                            (document["doc_id"],),
                        )
                        conn.execute(
                            "DELETE FROM entity_candidates WHERE doc_id=?",
                            (document["doc_id"],),
                        )
                        db.permanent_delete_document(conn, document["doc_id"])
                    st.success("Document and document-scoped records permanently deleted.")
                    st.rerun()

    if deleted_entities:
        st.subheader("Deleted Entities")
        for entity in deleted_entities:
            with st.container(border=True):
                st.markdown(f"**{entity['entity_id']} — {entity['canonical_name']}**")
                restore_col, delete_col = st.columns(2)
                if restore_col.button(
                    "Restore entity",
                    key=f"restore_ent_{entity['entity_id']}",
                    type="primary",
                ):
                    with db.get_connection() as conn:
                        db.restore_entity(conn, entity["entity_id"])
                    st.rerun()
                confirm = delete_col.checkbox(
                    "I understand this is irreversible",
                    key=f"confirm_delete_ent_{entity['entity_id']}",
                )
                if delete_col.button(
                    "Permanently delete entity",
                    key=f"permanent_ent_{entity['entity_id']}",
                    disabled=not confirm,
                ):
                    with db.get_connection() as conn:
                        # Remove dependent relations/evidence and mentions
                        # before the canonical entity to satisfy FK constraints.
                        conn.execute(
                            """DELETE FROM evidence_bundles
                               WHERE relationship_id IN (
                                 SELECT relationship_id FROM relationships
                                 WHERE source_entity_id=? OR target_entity_id=?
                               )""",
                            (entity["entity_id"], entity["entity_id"]),
                        )
                        conn.execute(
                            """DELETE FROM relationships
                               WHERE source_entity_id=? OR target_entity_id=?""",
                            (entity["entity_id"], entity["entity_id"]),
                        )
                        conn.execute("DELETE FROM mentions WHERE entity_id=?", (entity["entity_id"],))
                        conn.execute("DELETE FROM entities WHERE entity_id=?", (entity["entity_id"],))
                    st.success("Entity permanently deleted.")
                    st.rerun()





def _candidate_phrase_options(passage_text: str, start: int, end: int) -> dict[str, tuple[int, int]]:
    """Suggest the recognised span plus nearby single words and phrases."""
    import re

    spans: dict[str, tuple[int, int]] = {}
    if 0 <= start < end <= len(passage_text):
        spans[passage_text[start:end]] = (start, end)

    # Whitespace-token spans are a deliberately transparent suggestion
    # mechanism, not a claim of Bengali linguistic tokenisation.
    tokens = list(re.finditer(r"\S+", passage_text))
    overlapping = [
        i for i, token in enumerate(tokens)
        if token.start() < end and token.end() > start
    ]
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

        # Single-token candidates in the immediate context are also offered.
        for index in range(max(0, first - 2), min(len(tokens), last + 3)):
            token = tokens[index]
            phrase = passage_text[token.start():token.end()]
            spans.setdefault(phrase, (token.start(), token.end()))

    return spans


def page_ai_review() -> None:
    components.page_header(
        "AI Candidate Review",
        "Choose a suggested word or phrase, then accept, link, reject or defer it.",
    )
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
                progress.progress(
                    current / total if total else 1.0,
                    text=f"Scanning passage {current} of {total}",
                )

            found = ai_recognizer.recognize_candidates(
                passages, category_map, entities, progress_callback=progress_update
            )
            with db.get_connection() as conn:
                count = db.bulk_save_candidates(conn, found)
            progress.empty()
            st.success(f"{count} candidate(s) added to the review queue.")
            st.rerun()
        except Exception as exc:
            progress.empty()
            st.error(f"Recognition failed: {exc}")

    with db.get_connection() as conn:
        total = db.count_candidates(conn, doc_id)
        candidates = db.get_candidates_paginated(conn, doc_id, 100, 0)
        entities = db.get_entities(conn, profile_id)

    st.caption(f"{total} pending candidate(s).")
    if not candidates:
        st.info("No pending candidates in this document.")
        return

    categories_by_name = {c["name"]: c["category_id"] for c in categories}
    entity_options = {
        f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"]
        for e in entities
    }

    for candidate in candidates:
        with st.container(border=True):
            passage_text = candidate["passage_text"] or ""
            start, end = int(candidate["char_start"]), int(candidate["char_end"])
            suggestions = _candidate_phrase_options(passage_text, start, end)
            suggestion_labels = list(suggestions)
            st.markdown(f"**Recognition suggestion:** `{candidate['surface_form']}`")
            st.caption(
                f"Method: {candidate['recognition_method'] or 'unspecified'} · "
                f"Confidence: {candidate['confidence_score']}"
            )
            if candidate["contextual_evidence"]:
                st.write(candidate["contextual_evidence"])

            selected_phrase = st.selectbox(
                "Select a single word or phrase from the suggestions",
                suggestion_labels,
                index=(
                    suggestion_labels.index(candidate["surface_form"])
                    if candidate["surface_form"] in suggestion_labels else 0
                ),
                key=f"candidate_phrase_{candidate['candidate_id']}",
            )
            phrase_start, phrase_end = suggestions[selected_phrase]
            context_start = max(0, phrase_start - 80)
            context_end = min(len(passage_text), phrase_end + 80)
            st.text(passage_text[context_start:context_end])

            suggested_category = candidate["suggested_category_name"]
            category_names = list(categories_by_name)
            if not category_names:
                st.warning("No categories exist in the taxonomy.")
                continue
            category_index = (
                category_names.index(suggested_category)
                if suggested_category in category_names else 0
            )
            category = st.selectbox(
                "Category",
                category_names,
                index=category_index,
                key=f"candidate_category_v2_{candidate['candidate_id']}",
            )
            decision = st.radio(
                "Decision",
                ["Link to existing entity", "Create new entity", "Reject", "Defer"],
                horizontal=True,
                key=f"candidate_decision_{candidate['candidate_id']}",
            )

            linked_entity = None
            new_name = selected_phrase
            if decision == "Link to existing entity":
                if entity_options:
                    linked_entity = st.selectbox(
                        "Existing entity",
                        list(entity_options),
                        key=f"candidate_link_entity_{candidate['candidate_id']}",
                    )
                else:
                    st.info("No existing entity. Choose Create new entity.")
            elif decision == "Create new entity":
                new_name = st.text_input(
                    "Canonical entity name",
                    value=selected_phrase,
                    key=f"candidate_canonical_{candidate['candidate_id']}",
                )

            if st.button(
                "Apply researcher decision",
                type="primary",
                key=f"candidate_apply_v2_{candidate['candidate_id']}",
            ):
                if decision == "Defer":
                    st.info("Candidate remains pending.")
                elif decision == "Reject":
                    with db.get_connection() as conn:
                        db.update_candidate_status(conn, candidate["candidate_id"], "rejected")
                    st.rerun()
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
                                conn.execute(
                                    """INSERT INTO entities
                                    (entity_id, profile_id, canonical_name, category_id, created_at)
                                    VALUES (?, ?, ?, ?, ?)""",
                                    (
                                        entity_id, profile_id, new_name.strip(),
                                        categories_by_name[category], db.utc_now(),
                                    ),
                                )
                            db.save_mention(
                                conn,
                                entity_id=entity_id,
                                doc_id=doc_id,
                                passage_id=candidate["passage_id"],
                                surface_form=selected_phrase,
                                char_start=phrase_start,
                                char_end=phrase_end,
                            )
                            db.update_candidate_status(
                                conn, candidate["candidate_id"], "accepted"
                            )
                        st.success("Selected phrase has been annotated.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not save this annotation: {exc}")


def page_relationships() -> None:
    """Create and inspect document-scoped relationships using the real schema."""
    components.page_header(
        "Relationship Management",
        "Connect canonical entities within a selected research document.",
    )
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)
    if not documents or not profiles:
        st.info("Import documents and create a taxonomy profile first.")
        return

    profile_id = profiles[0]["profile_id"]
    with db.get_connection() as conn:
        entities = db.get_entities(conn, profile_id)
        rel_types = db.get_relationship_types(conn, profile_id)
    if len(entities) < 2 or not rel_types:
        st.info("Register at least two entities and relationship types first.")
        return

    doc_options = make_document_options(documents)
    selected_doc = st.selectbox("Research document", list(doc_options), key="rel_doc_v2")
    doc_id = doc_options[selected_doc]
    entity_options = {
        f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"]
        for e in entities
    }
    type_options = {r["name"]: r["type_id"] for r in rel_types}

    with db.get_connection() as conn:
        relations = conn.execute(
            """SELECT r.*, s.canonical_name AS source_name,
                      t.canonical_name AS target_name, rt.name AS type_name
               FROM relationships r
               JOIN entities s ON s.entity_id=r.source_entity_id
               JOIN entities t ON t.entity_id=r.target_entity_id
               JOIN relationship_types rt ON rt.type_id=r.type_id
               WHERE r.deleted_at IS NULL AND r.doc_id=?
               ORDER BY r.created_at DESC""",
            (doc_id,),
        ).fetchall()

    view_tab, add_tab = st.tabs(["Document Relationships", "Add Relationship"])
    with view_tab:
        if not relations:
            st.info("No relationships have been recorded for this document.")
        for relation in relations:
            with st.container(border=True):
                st.markdown(
                    f"**{relation['source_name']}** "
                    f"`[{relation['type_name']}]` "
                    f"**{relation['target_name']}**"
                )
                if relation["description"]:
                    st.write(relation["description"])
                st.caption(
                    f"{relation['relationship_id']} · "
                    f"Assessment: {relation['confidence'] or 'Unassessed'}"
                )
                with st.expander("Evidence and management"):
                    with db.get_connection() as conn:
                        evidence = db.get_evidence_for_relationship(
                            conn, relation["relationship_id"]
                        )
                    for item in evidence:
                        st.markdown(f"**{item['evidence_domain']}**")
                        st.write(item["source_text"])
                        if item["context"]:
                            st.caption(item["context"])
                    with st.form(f"add_rel_evidence_{relation['relationship_id']}"):
                        domain = st.selectbox(
                            "Evidence domain",
                            ["Literary", "Historical", "Geographical"],
                            key=f"ev_domain_{relation['relationship_id']}",
                        )
                        source_text = st.text_area(
                            "Evidence text",
                            key=f"ev_text_{relation['relationship_id']}",
                        )
                        context = st.text_input(
                            "Reference/context",
                            key=f"ev_context_{relation['relationship_id']}",
                        )
                        add = st.form_submit_button("Attach evidence")
                    if add:
                        if not source_text.strip():
                            st.error("Evidence text is required.")
                        else:
                            with db.get_connection() as conn:
                                db.add_evidence_bundle(
                                    conn, relation["relationship_id"],
                                    domain, source_text.strip(), context.strip(),
                                )
                            st.rerun()
                    confirm = st.checkbox(
                        "Confirm moving this relationship to Trash",
                        key=f"confirm_rel_trash_{relation['relationship_id']}",
                    )
                    if st.button(
                        "Move relationship to Trash",
                        disabled=not confirm,
                        key=f"trash_rel_v2_{relation['relationship_id']}",
                    ):
                        with db.get_connection() as conn:
                            conn.execute(
                                "UPDATE relationships SET deleted_at=? WHERE relationship_id=?",
                                (db.utc_now(), relation["relationship_id"]),
                            )
                        st.rerun()

    with add_tab:
        with st.form("add_doc_scoped_relationship_v2"):
            source = st.selectbox("Source entity", list(entity_options))
            target = st.selectbox("Target entity", list(entity_options))
            relation_type = st.selectbox("Relationship type", list(type_options))
            description = st.text_area("Description / interpretation")
            assessment = st.selectbox(
                "Research assessment",
                ["Unassessed", "Tentative", "Moderate", "Strong", "Contested"],
            )
            save = st.form_submit_button("Save relationship", type="primary")
        if save:
            if source == target:
                st.error("Source and target must be different.")
            else:
                with db.get_connection() as conn:
                    relation_id = db.next_relationship_id(conn)
                    conn.execute(
                        """INSERT INTO relationships
                        (relationship_id, source_entity_id, target_entity_id,
                         type_id, description, doc_id, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            relation_id, entity_options[source], entity_options[target],
                            type_options[relation_type], description.strip(),
                            doc_id, assessment, db.utc_now(),
                        ),
                    )
                st.success("Document-scoped relationship saved.")
                st.rerun()



# ---------------------------------------------------------------------
# NAVIGATION
# ---------------------------------------------------------------------

navigation = st.navigation(
    {
        "Workspace": [
            st.Page(
                page_dashboard,
                title="Dashboard",
                icon=":material/dashboard:",
                default=True,
            ),
            st.Page(
                page_projects,
                title="Projects & Corpora",
                icon=":material/folder_special:",
            ),
            st.Page(
                page_documents,
                title="Documents",
                icon=":material/folder_open:",
            ),
            st.Page(
                page_reader,
                title="Document Reader",
                icon=":material/menu_book:",
            ),
        ],
        "Analysis": [
            st.Page(
                page_text_analysis,
                title="Text Analysis",
                icon=":material/analytics:",
            ),
            st.Page(
                page_network_analysis,
                title="Network Analysis",
                icon=":material/hub:",
            ),
            st.Page(
                page_spatial_analysis,
                title="Spatial Analysis",
                icon=":material/map:",
            ),
        ],
        "Annotation": [
            st.Page(
                page_manual_annotation,
                title="Manual Annotation",
                icon=":material/edit_note:",
            ),
            st.Page(
                page_ai_review,
                title="AI Candidate Review",
                icon=":material/psychology:",
            ),
            st.Page(
                page_entities,
                title="Entity Catalogue",
                icon=":material/category:",
            ),
            st.Page(
                page_relationships,
                title="Relationships",
                icon=":material/link:",
            ),
        ],
        "Configuration": [
            st.Page(
                page_taxonomy_manager,
                title="Taxonomy Manager",
                icon=":material/account_tree:",
            ),
            st.Page(
                page_trash,
                title="Trash & Recovery",
                icon=":material/delete:",
            ),
            st.Page(
                page_export,
                title="Export Centre",
                icon=":material/download:",
            ),
            st.Page(
                settings_page.render_settings,
                title="Settings",
                icon=":material/settings:",
            ),
        ],
    }
)

navigation.run()
