"""TextEncode — Streamlit application entry point.

Run from the project root:

    streamlit run app.py
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
from modules import parser, processor, exporter

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
        "Humanities research."
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

    with st.expander("Current limitations"):
        st.markdown(
            "- Word counts are **approximate**: tokens are split on whitespace "
            "and edge punctuation is trimmed. Bengali compounds and sandhi forms "
            "are not segmented linguistically.\n"
            "- Sentence counts split on `। . ! ?` and over-count abbreviations.\n"
            "- Markdown is parsed as **CommonMark**: GFM tables are not yet "
            "supported.\n"
            "- A changed file is imported as a **new document** (new DOC id). "
            "Annotations never move to different text silently."
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
            except Exception as exc:
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
            "Deleting a document also deletes its passages and any mentions "
            "linked to them. This cannot be undone."
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
        with db.get_connection() as conn:
            source_text = "\n\n".join(
                conn.execute(
                    "SELECT source_text FROM documents WHERE doc_id = ?",
                    (d["doc_id"],),
                ).fetchone()[0]
                for d in documents
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
        "। . ! ? sentence splitting."
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
               "only; use Mention Registration to verify them.")

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


def page_entities() -> None:
    st.header("Entity Registration")
    st.write(
        "Register the concepts, people, places and things you find in your "
        "documents. Remember: an Entity is the concept (e.g., 'ইছামতী'), "
        "not the specific occurrences in the text."
    )

    with db.get_connection() as conn:
        categories = db.get_categories(conn)
        documents = db.list_documents(conn)
        entities = db.get_entities(conn)

    cat_options = {c["name"]: c["category_id"] for c in categories}
    doc_options = {"None": None}
    doc_options.update({f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents})

    tab_add, tab_manage = st.tabs(["➕ Register New Entity", "📋 Manage Entities"])

    # --- TAB 1: ADD ENTITY ---
    with tab_add:
        with st.form("add_entity_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            canonical_name = col1.text_input("Canonical Name *", placeholder="e.g. ইছামতী")
            category_name = col2.selectbox("Category *", list(cat_options.keys()))
            
            col3, col4 = st.columns(2)
            alt_names = col3.text_input("Alternative Names / Spellings", placeholder="Comma separated")
            transliteration = col4.text_input("Transliteration", placeholder="e.g. Ichhamati")
            
            description = st.text_area("Description")
            notes = st.text_area("Research Notes")
            
            assoc_doc = st.selectbox("Associated Document (Optional)", list(doc_options.keys()))
            
            submitted = st.form_submit_button("Save Entity", type="primary")
            
            if submitted:
                if not canonical_name.strip():
                    st.error("Canonical Name is required.")
                else:
                    try:
                        with db.get_connection() as conn:
                            new_id = db.save_entity(
                                conn,
                                canonical_name=canonical_name.strip(),
                                category_id=cat_options[category_name],
                                alt_names=alt_names.strip() or None,
                                transliteration=transliteration.strip() or None,
                                description=description.strip() or None,
                                notes=notes.strip() or None,
                                doc_id=doc_options[assoc_doc]
                            )
                        st.success(f"Entity saved successfully as {new_id}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving entity: {e}")

    # --- TAB 2: MANAGE / EDIT ENTITIES ---
    with tab_manage:
        if not entities:
            st.info("No entities registered yet.")
        else:
            entity_labels = {f"{e['entity_id']} — {e['canonical_name']} ({e['category']})": e for e in entities}
            selected_label = st.selectbox("Select an entity to view or edit", list(entity_labels.keys()))
            selected_entity = entity_labels[selected_label]

            with st.form("edit_entity_form"):
                st.subheader(f"Editing {selected_entity['entity_id']}")
                
                e_col1, e_col2 = st.columns(2)
                e_name = e_col1.text_input("Canonical Name", value=selected_entity["canonical_name"])
                
                current_cat_index = list(cat_options.keys()).index(selected_entity["category"])
                e_cat = e_col2.selectbox("Category", list(cat_options.keys()), index=current_cat_index)
                
                e_alt = st.text_input("Alternative Names", value=selected_entity["alt_names"] or "")
                e_trans = st.text_input("Transliteration", value=selected_entity["transliteration"] or "")
                e_desc = st.text_area("Description", value=selected_entity["description"] or "")
                e_notes = st.text_area("Research Notes", value=selected_entity["notes"] or "")

                col_save, col_del = st.columns([1, 1])
                save_btn = col_save.form_submit_button("Update Entity", type="primary")
                delete_btn = col_del.form_submit_button("Delete Entity", type="secondary")

                if save_btn:
                    with db.get_connection() as conn:
                        db.update_entity(
                            conn, selected_entity["entity_id"],
                            canonical_name=e_name.strip(),
                            category_id=cat_options[e_cat],
                            alt_names=e_alt.strip() or None,
                            transliteration=e_trans.strip() or None,
                            description=e_desc.strip() or None,
                            notes=e_notes.strip() or None
                        )
                    st.success("Entity updated.")
                    st.rerun()

                if delete_btn:
                    with db.get_connection() as conn:
                        db.delete_entity(conn, selected_entity["entity_id"])
                    st.warning(f"Deleted {selected_entity['entity_id']}.")
                    st.rerun()

            st.divider()
            st.subheader("All Registered Entities")
            df = pd.DataFrame([dict(e) for e in entities])
            st.dataframe(
                df[["entity_id", "canonical_name", "category", "alt_names", "description"]], 
                hide_index=True
            )


def page_mentions() -> None:
    st.header("Mention Registration")
    st.write(
        "A Mention records exactly where an Entity appears in the text. "
        "Select an entity, find the passage, and confirm the exact text."
    )

    with db.get_connection() as conn:
        entities = db.get_entities(conn)
        documents = db.list_documents(conn)
        mentions = db.get_mentions(conn)

    if not entities:
        st.warning("You must register at least one Entity before you can add Mentions.")
        return

    tab_add, tab_view = st.tabs(["➕ Register Mention", "📋 View Mentions"])

    # --- TAB 1: ADD MENTION ---
    with tab_add:
        entity_options = {f"{e['entity_id']} — {e['canonical_name']} ({e['category']})": e["entity_id"] for e in entities}
        selected_entity_label = st.selectbox("1. Select Entity *", list(entity_options.keys()))
        entity_id = entity_options[selected_entity_label]

        doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
        if not doc_options:
            st.info("You need to import a document first.")
            return
        
        selected_doc_label = st.selectbox("2. Select Document *", list(doc_options.keys()))
        doc_id = doc_options[selected_doc_label]

        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)

        if not passages:
            st.warning("This document has no passages.")
            return

        passage_options = {
            f"{p['passage_id']} (Chars {p['char_start']}-{p['char_end']}): {p['plain_text'][:60]}...": p["passage_id"]
            for p in passages
        }
        selected_passage_label = st.selectbox("3. Select Passage *", list(passage_options.keys()))
        passage_id = passage_options[selected_passage_label]

        selected_passage = next(p for p in passages if p["passage_id"] == passage_id)
        st.info(f"**Passage Text:**\n\n{selected_passage['plain_text']}")

        with st.form("add_mention_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            surface_form = col1.text_input(
                "Exact Text / Surface Form *", 
                value=selected_entity_label.split(" — ")[1].split(" (")[0],
                help="The exact spelling used in this specific passage."
            )
            note = col2.text_input("Research Note (optional)")
            
            submitted = st.form_submit_button("Save Mention", type="primary")
            
            if submitted:
                if not surface_form.strip():
                    st.error("Surface Form is required.")
                else:
                    try:
                        with db.get_connection() as conn:
                            new_id = db.save_mention(
                                conn,
                                entity_id=entity_id,
                                doc_id=doc_id,
                                passage_id=passage_id,
                                surface_form=surface_form.strip(),
                                note=note.strip() or None
                            )
                        st.success(f"Mention saved successfully as {new_id}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving mention: {e}")

    # --- TAB 2: VIEW MENTIONS ---
    with tab_view:
        if not mentions:
            st.info("No mentions registered yet.")
        else:
            df = pd.DataFrame([dict(m) for m in mentions])
            
            st.subheader("All Mentions")
            st.dataframe(
                df[["mention_id", "entity_id", "canonical_name", "surface_form", "passage_id", "plain_text"]],
                hide_index=True,
                column_config={
                    "plain_text": st.column_config.TextColumn("Context", width="large")
                }
            )

            st.divider()
            st.subheader("Delete a Mention")
            del_label = st.selectbox(
                "Select a mention to delete", 
                df["mention_id"] + " — " + df["canonical_name"] + " in " + df["passage_id"]
            )
            if st.button("Delete Mention", type="secondary"):
                mention_id = del_label.split(" — ")[0]
                with db.get_connection() as conn:
                    db.delete_mention(conn, mention_id)
                st.warning(f"Deleted {mention_id}.")
                st.rerun()


def page_relationships() -> None:
    st.header("Relationship Registration")
    st.write(
        "Connect two Entities with a specific relationship. "
        "Always provide evidence from a passage to support your interpretation."
    )

    with db.get_connection() as conn:
        entities = db.get_entities(conn)
        documents = db.list_documents(conn)
        rel_types = db.get_relationship_types(conn)
        relationships = db.get_relationships(conn)

    if len(entities) < 2:
        st.warning("You need at least two Entities registered before you can create a Relationship.")
        return

    tab_add, tab_view = st.tabs(["➕ Register Relationship", "📋 View Relationships"])

    # --- TAB 1: ADD RELATIONSHIP ---
    with tab_add:
        entity_options = {f"{e['entity_id']} — {e['canonical_name']} ({e['category']})": e["entity_id"] for e in entities}
        rel_type_options = {f"{rt['name']} ({rt['description']})": rt["type_id"] for rt in rel_types}

        col1, col2 = st.columns(2)
        source_label = col1.selectbox("Source Entity *", list(entity_options.keys()))
        target_label = col2.selectbox("Target Entity *", list(entity_options.keys()))
        
        source_id = entity_options[source_label]
        target_id = entity_options[target_label]

        rel_type_label = st.selectbox("Relationship Type *", list(rel_type_options.keys()))
        type_id = rel_type_options[rel_type_label]

        description = st.text_area("Description / Interpretation", placeholder="e.g. The fishing community relies on the river for their livelihood.")
        confidence = st.selectbox("Confidence", ["Unspecified", "low", "medium", "high"])

        # Evidence Passage (Optional but recommended)
        st.subheader("Evidence (Optional)")
        doc_options = {"None": None}
        doc_options.update({f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents})
        selected_doc_label = st.selectbox("Select Document", list(doc_options.keys()))
        doc_id = doc_options[selected_doc_label]

        evidence_passage_id = None
        if doc_id:
            with db.get_connection() as conn:
                passages = db.get_passages(conn, doc_id)
            
            passage_options = {
                f"{p['passage_id']}: {p['plain_text'][:60]}...": p["passage_id"]
                for p in passages
            }
            # Add a "None" option for evidence
            passage_options = {"None": None, **passage_options}
            
            selected_passage_label = st.selectbox("Select Evidence Passage", list(passage_options.keys()))
            evidence_passage_id = passage_options[selected_passage_label]

            if evidence_passage_id:
                selected_passage = next(p for p in passages if p["passage_id"] == evidence_passage_id)
                st.info(f"**Passage Text:**\n\n{selected_passage['plain_text']}")

        if st.button("Save Relationship", type="primary"):
            if source_id == target_id:
                st.error("Source and Target entities must be different.")
            elif not description.strip():
                st.error("Please provide a description/interpretation.")
            else:
                try:
                    with db.get_connection() as conn:
                        new_id = db.save_relationship(
                            conn,
                            source_entity_id=source_id,
                            target_entity_id=target_id,
                            type_id=type_id,
                            description=description.strip(),
                            evidence_passage_id=evidence_passage_id,
                            doc_id=doc_id,
                            confidence=None if confidence == "Unspecified" else confidence
                        )
                    st.success(f"Relationship saved successfully as {new_id}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving relationship: {e}")

    # --- TAB 2: VIEW RELATIONSHIPS ---
    with tab_view:
        if not relationships:
            st.info("No relationships registered yet.")
        else:
            df = pd.DataFrame([dict(r) for r in relationships])
            
            st.subheader("All Relationships")
            st.dataframe(
                df[["relationship_id", "source_name", "relationship_type", "target_name", "confidence", "evidence_passage_id"]],
                hide_index=True
            )

            st.divider()
            st.subheader("Relationship Details")
            rel_label = st.selectbox(
                "Select a relationship to view details", 
                df["relationship_id"] + " — " + df["source_name"] + " " + df["relationship_type"] + " " + df["target_name"]
            )
            rel_id = rel_label.split(" — ")[0]
            selected_rel = next(r for r in relationships if r["relationship_id"] == rel_id)

            st.write(f"**Description:** {selected_rel['description']}")
            if selected_rel['evidence_text']:
                st.info(f"**Evidence from {selected_rel['evidence_passage_id']}:**\n\n{selected_rel['evidence_text']}")
            else:
                st.caption("No evidence passage linked.")

            if st.button("Delete Relationship", type="secondary"):
                with db.get_connection() as conn:
                    db.delete_relationship(conn, rel_id)
                st.warning(f"Deleted {rel_id}.")
                st.rerun()


def page_export() -> None:
    st.header("Export Data")
    st.write(
        "Export your structured research data. The CSV and JSON files contain "
        "the raw database tables. The TEI XML export creates a standards-based "
        "text encoding with your entities linked to their passages."
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if not documents:
        st.info("No data to export yet. Import and annotate a document first.")
        return

    # --- CSV & JSON EXPORTS ---
    with db.get_connection() as conn:
        # JSON Export
        combined_json = exporter.generate_json_export(conn)
        st.download_button(
            "Download Complete Dataset (JSON)",
            data=combined_json.encode("utf-8"),
            file_name="textencode_dataset.json",
            mime="application/json",
            use_container_width=True,
        )

    st.divider()

    # --- TEI XML EXPORT ---
    st.subheader("TEI P5 XML Export")
    st.caption(
        "⚠️ **Note:** This is a basic TEI-compatible export. It uses inline "
        "tags (e.g., `<persName>`) and a `<standOff>` for entity lists. It is "
        "*not* strictly schema-validated against the full TEI ODD."
    )

    doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
    selected_doc_label = st.selectbox("Select a document to encode as TEI", list(doc_options.keys()))
    
    if st.button("Generate TEI XML"):
        doc_id = doc_options[selected_doc_label]
        with db.get_connection() as conn:
            xml_string = exporter.generate_tei_xml(conn, doc_id)
        
        st.download_button(
            "Download TEI XML",
            data=xml_string.encode("utf-8"),
            file_name=f"textencode_{doc_id}.xml",
            mime="application/xml"
        )
        
        with st.expander("Preview XML"):
            st.code(xml_string, language="xml")


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
            "- Mention offsets are relative to `passages.text`.\n"
            "- Identical files are refused; changed files become new documents."
        )


PAGES = {
    "Dashboard": page_dashboard,
    "Import Documents": page_import,
    "Document Reader": page_reader,
    "Text Statistics": page_statistics,
    "Keyword Search": page_search,
    "Entity Registration": page_entities,
    "Mention Registration": page_mentions,
    "Relationship Registration": page_relationships,
    "Export Data": page_export,
    "Settings": page_settings,
}

with st.sidebar:
    st.markdown("### 📖 TextEncode")
    choice = st.radio("Navigation", list(PAGES))
    st.caption("Stage 3 · exports & TEI")

PAGES[choice]()