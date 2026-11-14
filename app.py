"""TextEncode — Streamlit application entry point.

Run from the project root:

    streamlit run app.py

Stage 1 pages: Dashboard, Import Documents, Document Reader, Text Statistics,
Keyword Search, Settings. Entity/mention/relationship pages arrive in Stage 2.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Make sure `modules` and `database` are importable regardless of how
# Streamlit was launched (cwd is not always the project root on Windows).
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from database import db
from modules import parser, processor

PAGE_SIZE = 25

st.set_page_config(page_title="TextEncode", page_icon="📖", layout="wide")


@st.cache_resource
def _startup() -> str:
    """Create the database schema once per server process."""
    db.init_db()
    return str(db.DB_PATH)


DB_FILE = _startup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _document_labels(documents) -> dict[str, str]:
    """Map display label -> doc_id for selectboxes."""
    return {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}


def _passage_rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_dashboard() -> None:
    st.title("TextEncode")
    st.caption(
        "Markdown text processing, annotation and encoding for Digital "
        "Humanities research. Stage 1: document import and text processing."
    )

    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)

    cols = st.columns(5)
    cols[0].metric("Documents", stats["documents"])
    cols[1].metric("Passages", stats["passages"])
    cols[2].metric("Entities", stats["entities"])
    cols[3].metric("Mentions", stats["mentions"])
    cols[4].metric("Relationships", stats["relationships"])

    st.subheader("Documents")
    if not documents:
        st.info("No documents yet. Go to **Import Documents** to add a Markdown file.")
    else:
        table = pd.DataFrame([dict(d) for d in documents])
        st.dataframe(
            table[["doc_id", "title", "author", "language", "passage_count",
                   "import_date"]],
            hide_index=True,
        )

    with st.expander("Current limitations (read before using the statistics)"):
        st.markdown(
            "- Word counts are **approximate**: tokens are split on whitespace "
            "and edge punctuation is trimmed. Bengali compounds and sandhi forms "
            "are not segmented linguistically.\n"
            "- Sentence counts split on `। . ! ?` and over-count abbreviations.\n"
            "- Markdown is parsed as **CommonMark**: GFM tables are not yet "
            "supported.\n"
            "- A changed file is imported as a **new document** (new DOC id). "
            "Annotations never move to different text silently.\n"
            "- Entity, mention and relationship registration arrives in Stage 2."
        )


def page_import() -> None:
    st.header("Import Documents")
    st.write(
        "Upload one or more UTF-8 Markdown files. The original text is stored "
        "unchanged. Identical files are refused; a changed file becomes a new "
        "document."
    )

    uploaded = st.file_uploader(
        "Markdown files", type=["md", "markdown", "txt"],
        accept_multiple_files=True,
    )
    if not uploaded:
        st.info("Choose at least one file to begin.")
        return

    batch_language = st.text_input(
        "Language for this batch (optional)", placeholder="e.g. Bengali"
    )

    # Parse everything once per rerun: parsing is pure and fast, so no
    # session_state juggling is needed.
    parsed = []
    for uploaded_file in uploaded:
        try:
            text = uploaded_file.getvalue().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            parsed.append({"file": uploaded_file, "text": None,
                           "passages": None,
                           "error": f"Could not decode as UTF-8: {exc}"})
            continue
        try:
            passages = parser.parse_markdown(text)
        except ValueError as exc:
            parsed.append({"file": uploaded_file, "text": text,
                           "passages": None, "error": str(exc)})
            continue
        parsed.append({"file": uploaded_file, "text": text,
                       "passages": passages, "error": None})

    st.subheader("Files")
    metadata: dict[int, dict] = {}
    for index, item in enumerate(parsed):
        uploaded_file = item["file"]
        with st.expander(f"{uploaded_file.name}", expanded=True):
            if item["error"]:
                st.error(item["error"])
                continue

            passages = item["passages"]
            guessed = parser.guess_title(passages) or Path(uploaded_file.name).stem

            title = st.text_input("Title", value=guessed, key=f"title_{index}")
            col_a, col_b = st.columns(2)
            author = col_a.text_input(
                "Author (optional)", key=f"author_{index}"
            )
            language = col_b.text_input(
                "Language (optional)", value=batch_language, key=f"lang_{index}"
            )
            publication = st.text_input(
                "Publication information (optional)", key=f"pub_{index}"
            )

            metadata[index] = {
                "title": title.strip() or guessed,
                "author": author.strip() or None,
                "language": language.strip() or None,
                "publication_info": publication.strip() or None,
            }

            if not passages:
                st.warning("No passages detected. Is the file empty?")
            else:
                st.caption(f"{len(passages)} passages detected.")
                preview = pd.DataFrame([
                    {
                        "sequence": p["sequence"],
                        "type": p["passage_type"],
                        "chars": f"{p['char_start']}–{p['char_end']}",
                        "text": (p["plain_text"][:80] +
                                 ("…" if len(p["plain_text"]) > 80 else "")),
                    }
                    for p in passages[:10]
                ])
                st.dataframe(preview, hide_index=True)

    if st.button("Save to database", type="primary"):
        results = []
        for index, item in enumerate(parsed):
            name = item["file"].name
            if item["error"]:
                results.append({"file": name, "result": "skipped",
                                "detail": item["error"]})
                continue
            meta = metadata[index]
            try:
                with db.get_connection() as conn:
                    doc_id = db.save_document(
                        conn,
                        title=meta["title"],
                        original_filename=name,
                        source_text=item["text"],
                        passages=item["passages"],
                        language=meta["language"],
                        author=meta["author"],
                        publication_info=meta["publication_info"],
                    )
                results.append({
                    "file": name, "result": doc_id,
                    "detail": f"{len(item['passages'])} passages saved",
                })
            except db.DuplicateDocumentError as exc:
                results.append({"file": name, "result": "duplicate",
                                "detail": str(exc)})
            except Exception as exc:  # noqa: BLE001 - surface any failure
                results.append({"file": name, "result": "error",
                                "detail": str(exc)})

        st.subheader("Import results")
        st.dataframe(pd.DataFrame(results), hide_index=True)
        if any(r["result"] not in ("skipped", "duplicate", "error")
               for r in results):
            st.success("Import complete. Open **Document Reader** to inspect "
                       "the stored passages.")


def page_reader() -> None:
    st.header("Document Reader")

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents:
        st.info("No documents yet. Import a Markdown file first.")
        return

    labels = _document_labels(documents)
    label = st.selectbox("Document", list(labels))
    doc_id = labels[label]

    with db.get_connection() as conn:
        document = db.get_document(conn, doc_id)
        passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))

    meta_col, stats_col = st.columns([2, 1])
    with meta_col:
        st.subheader(document["title"])
        st.caption(
            f"{document['doc_id']} · {document['original_filename']} · "
            f"imported {document['import_date']}"
        )
        for field in ("author", "language", "publication_info"):
            if document[field]:
                st.write(f"**{field.replace('_', ' ').title()}:** {document[field]}")
    with stats_col:
        st.metric("Passages", len(passages))
        st.metric("Characters", len(document["source_text"]))

    st.download_button(
        "Download original Markdown",
        data=document["source_text"].encode("utf-8"),
        file_name=document["original_filename"],
        mime="text/markdown",
    )

    if not passages:
        st.warning("This document has no passages.")
        return

    available_types = sorted({p["passage_type"] for p in passages})
    chosen_types = st.multiselect(
        "Passage types", available_types, default=available_types
    )
    filtered = [p for p in passages if p["passage_type"] in chosen_types]
    show_raw = st.toggle("Show original Markdown source", value=False)

    if not filtered:
        st.warning("No passages match the current filter.")
        return

    pages = max(1, math.ceil(len(filtered) / PAGE_SIZE))
    page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1)
    start = (int(page) - 1) * PAGE_SIZE

    st.caption(f"{len(filtered)} passages · page {page} of {pages}")
    for passage in filtered[start:start + PAGE_SIZE]:
        with st.container(border=True):
            caption = (f"{passage['passage_id']} · {passage['passage_type']} · "
                       f"chars {passage['char_start']}–{passage['char_end']}")
            if passage["heading_path"]:
                caption += f" · {passage['heading_path']}"
            st.caption(caption)
            if show_raw:
                st.code(passage["text"], language=None)
            else:
                st.markdown(passage["plain_text"] or "*(empty passage)*")

    with st.expander("Danger zone: delete this document"):
        st.write(
            "Deleting a document also deletes its passages and (once Stage 2 "
            "exists) its mentions. This cannot be undone."
        )
        confirm = st.checkbox(
            f"I understand and want to delete {document['doc_id']}",
            key=f"confirm_delete_{doc_id}",
        )
        if st.button("Delete document", disabled=not confirm):
            with db.get_connection() as conn:
                db.delete_document(conn, doc_id)
            st.success(f"Deleted {doc_id}.")
            st.rerun()


def page_statistics() -> None:
    st.header("Text Statistics")

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        all_passages = _passage_rows_to_dicts(db.get_all_passages(conn))
    if not documents:
        st.info("No documents yet.")
        return

    scope = st.selectbox(
        "Scope", ["All documents"] + list(_document_labels(documents))
    )

    if scope == "All documents":
        source_text = "\n\n".join(
            d["source_text"] for d in
            (db.get_document(conn, d["doc_id"]) for d in documents)
        ) if False else None  # placeholder; replaced below
        with db.get_connection() as conn:
            source_text = "\n\n".join(
                row["source_text"]
                for row in (db.get_document(conn, d["doc_id"]) for d in documents)
            )
        passages = all_passages
    else:
        doc_id = _document_labels(documents)[scope]
        with db.get_connection() as conn:
            source_text = db.get_document(conn, doc_id)["source_text"]
            passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))

    stats = processor.document_statistics(source_text, passages)

    row1 = st.columns(4)
    row1[0].metric("Words (approx.)", stats["word_count"])
    row1[1].metric("Unique words", stats["unique_word_count"])
    row1[2].metric("Sentences (approx.)", stats["sentence_count"])
    row1[3].metric("Characters", stats["char_count"])

    row2 = st.columns(4)
    row2[0].metric("Passages", stats["passage_count"])
    row2[1].metric("Headings", stats["heading_count"])
    row2[2].metric("Paragraphs", stats["paragraph_count"])
    row2[3].metric("List items", stats["list_item_count"])

    st.caption(
        "Word and sentence counts are approximate: whitespace tokenisation and "
        "। . ! ? sentence splitting. See the limitations note on the Dashboard."
    )

    st.subheader("Word frequency")
    limit = st.slider("Number of tokens", 10, 200, 50, step=10)
    frequencies = processor.word_frequencies(
        processor.analysable_text(passages), limit=limit
    )
    if not frequencies:
        st.info("No text to analyse.")
        return

    table = pd.DataFrame(frequencies, columns=["token", "count"])
    st.dataframe(table, hide_index=True)
    st.download_button(
        "Download frequencies as CSV",
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name="textencode_word_frequencies.csv",
        mime="text/csv",
    )


def page_search() -> None:
    st.header("Keyword Search")
    st.caption("Search runs on the readable passage text. Matches are suggestions "
               "only; Stage 2 will let you verify them as mentions.")

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        all_passages = _passage_rows_to_dicts(db.get_all_passages(conn))
    if not documents:
        st.info("No documents yet.")
        return

    scope = st.selectbox(
        "Scope", ["All documents"] + list(_document_labels(documents)),
        key="search_scope",
    )
    query = st.text_input("Search term", placeholder="e.g. ইছামতী or river")
    case_sensitive = st.checkbox("Case sensitive (Latin script only)", value=False)

    if not query.strip():
        st.info("Enter a search term.")
        return

    if scope == "All documents":
        passages = all_passages
    else:
        doc_id = _document_labels(documents)[scope]
        with db.get_connection() as conn:
            passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))

    results = processor.search_passages(
        passages, query, case_sensitive=case_sensitive
    )

    if not results:
        st.warning("No matches found.")
        return

    st.success(
        f"{len(results)} passages contain “{query}” "
        f"({sum(r['match_count'] for r in results)} matches in total)."
    )

    summary = pd.DataFrame([
        {
            "passage_id": r["passage_id"],
            "doc_id": r["doc_id"],
            "type": r["passage_type"],
            "matches": r["match_count"],
            "heading": r["heading_path"],
        }
        for r in results
    ])
    st.dataframe(summary, hide_index=True)

    st.subheader("Context")
    for result in results:
        with st.expander(
            f"{result['passage_id']} · {result['match_count']} match(es)"
        ):
            for snippet in result["snippets"]:
                st.write(snippet)


def page_settings() -> None:
    st.header("Settings")
    st.write(f"**Database file:** `{DB_FILE}`")
    with db.get_connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        stats = db.database_stats(conn)
    st.write(f"**Schema version:** {version}")
    st.write("**Row counts:**")
    st.dataframe(
        pd.DataFrame([stats]).T.rename(columns={0: "count"}),
    )

    if Path(DB_FILE).exists():
        st.download_button(
            "Download database backup (.db)",
            data=Path(DB_FILE).read_bytes(),
            file_name="textencode_backup.db",
            mime="application/octet-stream",
        )

    with st.expander("Technical notes"):
        st.markdown(
            "- Database: SQLite, one file, WAL not enabled (single user).\n"
            "- IDs: `DOC-001`, `DOC-001-P001`, `ENT-000001`, `MEN-000001`, "
            "`REL-000001`.\n"
            "- Passage offsets are Python string indices (Unicode code points) "
            "into `documents.source_text`; "
            "`source_text[char_start:char_end] == passages.text` is guaranteed.\n"
            "- Mention offsets (Stage 2) are relative to `passages.text`.\n"
            "- Identical files are refused; changed files become new documents."
        )


PAGES = {
    "Dashboard": page_dashboard,
    "Import Documents": page_import,
    "Document Reader": page_reader,
    "Text Statistics": page_statistics,
    "Keyword Search": page_search,
    "Settings": page_settings,
}

with st.sidebar:
    st.markdown("### 📖 TextEncode")
    choice = st.radio("Navigation", list(PAGES))
    st.caption("Stage 1 · documents & passages")

PAGES[choice]()
