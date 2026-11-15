"""TextEncode — Streamlit application entry point."""

from __future__ import annotations

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from database import db
# Make sure taxonomy_ui is imported here!
from modules import parser, processor, exporter, linguistics, taxonomy_ui, ai_recognizer

PAGE_SIZE = 25

st.set_page_config(page_title="TextEncode", page_icon="📖", layout="wide")

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
    sorted_mentions = sorted(mentions, key=lambda m: m["char_start"], reverse=True)
    highlighted = text
    for m in sorted_mentions:
        start, end = m["char_start"], m["char_end"]
        if start is not None and end is not None and 0 <= start < end <= len(highlighted):
            if highlighted[start:end] == m["surface_form"]:
                tag = f"<mark title='{m['entity_id']}'>{highlighted[start:end]}</mark>"
                highlighted = highlighted[:start] + tag + highlighted[end:]
    return highlighted

# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_dashboard() -> None:
    st.title("TextEncode v0.3")
    with db.get_connection() as conn:
        stats = db.database_stats(conn)
        documents = db.list_documents(conn)
    cols = st.columns(5)
    cols[0].metric("Documents", stats["documents"])
    cols[1].metric("Passages", stats["passages"])
    cols[2].metric("Entities", stats["entities"])
    cols[3].metric("Mentions", stats["mentions"])
    cols[4].metric("Relationships", stats["relationships"])
    if documents:
        st.dataframe(pd.DataFrame([dict(d) for d in documents])[["doc_id", "title", "passage_count"]], hide_index=True)

def page_import() -> None:
    st.header("Import Documents")
    uploaded = st.file_uploader("Markdown files", type=["md", "markdown", "txt"], accept_multiple_files=True)
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

def page_reader() -> None:
    st.header("Document Reader")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents: return
    doc_id = _document_labels(documents)[st.selectbox("Document", list(_document_labels(documents)))]
    with db.get_connection() as conn:
        document = db.get_document(conn, doc_id)
        total_passages = db.count_passages(conn, doc_id)
        # Fetch all mentions for this document to highlight them
        all_mentions = [dict(m) for m in db.get_mentions_for_document(conn, doc_id)] if hasattr(db, 'get_mentions_for_document') else []

    mentions_by_passage = {}
    for m in all_mentions:
        mentions_by_passage.setdefault(m["passage_id"], []).append(m)

    pages = max(1, math.ceil(total_passages / PAGE_SIZE))
    page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1)
    offset = (int(page) - 1) * PAGE_SIZE

    with db.get_connection() as conn:
        passages = _passage_rows_to_dicts(db.get_passages_paginated(conn, doc_id, PAGE_SIZE, offset))

    for p in passages:
        with st.container(border=True):
            st.caption(f"{p['passage_id']} · chars {p['char_start']}–{p['char_end']}")
            p_mentions = mentions_by_passage.get(p["passage_id"], [])
            highlighted_text = highlight_mentions(p["plain_text"], p_mentions)
            st.markdown(highlighted_text, unsafe_allow_html=True)

@st.cache_data
def _cached_document_statistics(source_text: str, passages: list[dict]) -> dict:
    return processor.document_statistics(source_text, passages)
@st.cache_data
def _cached_word_frequencies(text: str, limit: int | None) -> list[tuple[str, int]]:
    return processor.word_frequencies(text, limit=limit)
@st.cache_data
def _cached_lemma_frequencies(text: str, limit: int | None) -> list[tuple[str, int]]:
    return linguistics.lemma_frequencies(text, limit=limit)

def page_statistics() -> None:
    st.header("Text Statistics")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        all_passages = _passage_rows_to_dicts(db.get_all_passages(conn))
    if not documents: return
    scope = st.selectbox("Scope", ["All documents"] + list(_document_labels(documents)))
    if scope == "All documents":
        with db.get_connection() as conn:
            source_text = "\n\n".join(conn.execute("SELECT source_text FROM documents WHERE doc_id = ?", (d["doc_id"],)).fetchone()[0] for d in documents)
        passages = all_passages
    else:
        doc_id = _document_labels(documents)[scope]
        with db.get_connection() as conn:
            source_text = db.get_document(conn, doc_id)["source_text"]
            passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))

    stats = _cached_document_statistics(source_text, passages)
    st.columns(4)[0].metric("Words", stats["word_count"])
    st.columns(4)[1].metric("Unique words", stats["unique_word_count"])
    st.columns(4)[2].metric("Sentences", stats["sentence_count"])
    st.columns(4)[3].metric("Characters", stats["char_count"])

    show_all = st.checkbox("Calculate all unique words", value=False)
    limit = None if show_all else st.slider("Number of tokens", 10, 500, 50, step=10)
    frequencies = _cached_word_frequencies(processor.analysable_text(passages), limit=limit)
    if frequencies:
        table = pd.DataFrame(frequencies, columns=["token", "count"])
        st.dataframe(table.head(1000), hide_index=True)
        st.download_button("Download frequencies as CSV", data=table.to_csv(index=False).encode("utf-8-sig"), file_name="frequencies.csv", mime="text/csv")

def page_linguistics() -> None:
    st.header("Linguistic Analysis")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        all_passages = _passage_rows_to_dicts(db.get_all_passages(conn))
    if not documents: return
    scope = st.selectbox("Scope", ["All documents"] + list(_document_labels(documents)), key="ling_scope")
    if scope == "All documents":
        with db.get_connection() as conn:
            source_text = "\n\n".join(conn.execute("SELECT source_text FROM documents WHERE doc_id = ?", (d["doc_id"],)).fetchone()[0] for d in documents)
        passages = all_passages
    else:
        doc_id = _document_labels(documents)[scope]
        with db.get_connection() as conn:
            source_text = db.get_document(conn, doc_id)["source_text"]
            passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))

    body = processor.analysable_text(passages)
    show_all = st.checkbox("Calculate all lemmas", value=False)
    limit = None if show_all else st.slider("Number of lemmas", 10, 500, 50, step=10)

    frequencies = _cached_lemma_frequencies(body, limit=limit)
    word_map = linguistics.word_to_lemma_map(body)
    if frequencies:
        table = pd.DataFrame(frequencies, columns=["lemma", "count"])
        surface_forms = {}
        for word, lemma in word_map.items():
            surface_forms.setdefault(lemma, []).append(word)
        table["surface_forms"] = table["lemma"].apply(lambda x: ", ".join(surface_forms.get(x, [x])[:5]))
        st.dataframe(table.head(1000), hide_index=True)
        st.download_button("Download lemmas as CSV", data=table.to_csv(index=False).encode("utf-8-sig"), file_name="lemmas.csv", mime="text/csv")

def page_search() -> None:
    st.header("Keyword Search")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)
    if not documents: return
    scope = st.selectbox("Scope", ["All documents"] + list(_document_labels(documents)), key="search_scope")
    query = st.text_input("Search term", placeholder="e.g. ইছামতী or river")
    if not query.strip(): return
    doc_id = None if scope == "All documents" else _document_labels(documents)[scope]
    with db.get_connection() as conn:
        results = db.search_passages_fts(conn, query, doc_id)

    if not results: st.warning("No matches found.")
    else:
        st.success(f"{len(results)} passages contain “{query}”")
        for r in results[:100]:
            with st.expander(f"{r['passage_id']} — {r['doc_id']}"):
                st.write(r["plain_text"])

def page_entities() -> None:
    st.header("Entity Registration")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        categories = db.get_categories(conn, profile_id)
        documents = db.list_documents(conn)
        entities = db.get_entities(conn, profile_id)

    cat_options = {c["name"]: c["category_id"] for c in categories}
    doc_options = {"None": None}
    doc_options.update({f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents})

    tab_add, tab_manage = st.tabs(["➕ Register New Entity", "📋 Manage Entities"])
    
    with tab_add:
        # Note: We removed the st.form wrapper so the custom attributes can update dynamically based on category selection
        col1, col2 = st.columns(2)
        canonical_name = col1.text_input("Canonical Name *", placeholder="e.g. ইছামতী")
        category_name = col2.selectbox("Category *", list(cat_options.keys()))
        category_id = cat_options[category_name]
        
        alt_names = st.text_input("Alternative Names")
        description = st.text_area("Description")
        
        st.subheader("Geographical Metadata (Optional for QGIS)")
        col3, col4 = st.columns(2)
        lat = col3.number_input("Latitude", value=None, format="%.6f")
        lon = col4.number_input("Longitude", value=None, format="%.6f")
        loc_status = st.selectbox("Location Status", ["Uncertain", "Verified", "Approximate", "Historical", "Fictional"])

        # --- DYNAMIC CUSTOM METADATA ---
        st.subheader("Custom Metadata")
        with db.get_connection() as conn:
            # Fetch attribute definitions that apply to this category OR all entities (category_id IS NULL)
            attr_defs = conn.execute(
                "SELECT * FROM attribute_definitions WHERE profile_id = ? AND target_table = 'entities' AND (category_id IS NULL OR category_id = ?)",
                (profile_id, category_id)
            ).fetchall()
        
        custom_attr_values = {}
        if attr_defs:
            for attr in attr_defs:
                custom_attr_values[attr["attribute_id"]] = st.text_input(f"{attr['name']} ({attr['data_type']})")
        else:
            st.info("No custom metadata fields defined for this category in the Taxonomy Manager.")

        if st.button("Save Entity", type="primary"):
            if not canonical_name.strip(): 
                st.error("Canonical Name is required.")
            else:
                with db.get_connection() as conn:
                    new_id = db.save_entity(
                        conn, profile_id=profile_id, canonical_name=canonical_name.strip(), category_id=category_id, 
                        alt_names=alt_names.strip() or None, description=description.strip() or None,
                        latitude=lat, longitude=lon, location_status=loc_status
                    )
                    # Save custom attributes
                    for attr_id, val in custom_attr_values.items():
                        if val.strip():
                            db.save_attribute_value(conn, attribute_id=attr_id, entity_id=new_id, value_text=val.strip())
                
                st.success(f"Entity saved successfully as {new_id}.")
                st.rerun()

    with tab_manage:
        if entities:
            entity_labels = {f"{e['entity_id']} — {e['canonical_name']} ({e['category_name']})": e for e in entities}
            selected_entity = entity_labels[st.selectbox("Select an entity to edit", list(entity_labels.keys()))]
            
            # Display custom metadata for the selected entity
            with db.get_connection() as conn:
                attrs = db.get_attribute_values(conn, entity_id=selected_entity['entity_id'])
            if attrs:
                st.write("**Custom Metadata:**")
                for a in attrs:
                    st.write(f"- {a['name']}: {a['value_text']}")
            
            st.write(f"Editing {selected_entity['entity_id']}. (Full update UI would go here)")

def page_mentions() -> None:
    st.header("Mention Registration")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        entities = db.get_entities(conn, profile_id)
        documents = db.list_documents(conn)
        mentions = db.get_mentions(conn) if hasattr(db, 'get_mentions') else []

    if not entities:
        st.warning("You must register at least one Entity before you can add Mentions.")
        return

    tab_add, tab_view = st.tabs(["➕ Register Mention", "📋 View Mentions"])
    with tab_add:
        entity_options = {f"{e['entity_id']} — {e['canonical_name']} ({e['category_name']})": e["entity_id"] for e in entities}
        entity_id = entity_options[st.selectbox("1. Select Entity *", list(entity_options.keys()))]
        doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
        if not doc_options: return
        doc_id = doc_options[st.selectbox("2. Select Document *", list(doc_options.keys()))]
        
        with db.get_connection() as conn:
            passages = db.get_passages(conn, doc_id)

        if passages:
            passage_options = {f"{p['passage_id']}: {p['plain_text'][:60]}...": p["passage_id"] for p in passages}
            passage_id = passage_options[st.selectbox("3. Select Passage *", list(passage_options.keys()))]
            selected_passage = next(p for p in passages if p["passage_id"] == passage_id)
            st.info(f"**Passage Text:**\n\n{selected_passage['plain_text']}")

            with st.form("add_mention_form", clear_on_submit=True):
                surface_form = st.text_input("Exact Text / Surface Form *")
                note = st.text_input("Research Note (optional)")
                
                if st.form_submit_button("Save Character-Level Mention", type="primary"):
                    if not surface_form.strip(): st.error("Surface Form is required.")
                    else:
                        text = selected_passage["plain_text"]
                        start_idx = text.find(surface_form.strip())
                        if start_idx == -1:
                            st.error(f"Could not find '{surface_form}' in this passage.")
                        else:
                            end_idx = start_idx + len(surface_form.strip())
                            with db.get_connection() as conn:
                                new_id = db.save_mention(conn, entity_id=entity_id, doc_id=doc_id, passage_id=passage_id, surface_form=surface_form.strip(), char_start=start_idx, char_end=end_idx, note=note.strip() or None)
                            st.success(f"Mention saved as {new_id}.")
                            st.rerun()

    with tab_view:
        if mentions:
            df = pd.DataFrame([dict(m) for m in mentions])
            st.dataframe(df[["mention_id", "canonical_name", "surface_form", "passage_id"]], hide_index=True)

def page_relationships() -> None:
    st.header("Relationship Registration")
    with db.get_connection() as conn:
        profiles = db.get_profiles(conn)
        profile_id = profiles[0]["profile_id"] if profiles else 1
        entities = db.get_entities(conn, profile_id)
        rel_types = db.get_relationship_types(conn, profile_id)
        relationships = db.get_relationships(conn) if hasattr(db, 'get_relationships') else []

    if len(entities) < 2:
        st.warning("You need at least two Entities.")
        return

    tab_add, tab_view = st.tabs(["➕ Register", "📋 View"])
    with tab_add:
        entity_options = {f"{e['entity_id']} — {e['canonical_name']}": e["entity_id"] for e in entities}
        rel_type_options = {f"{rt['name']} ({rt['group_name']})": rt["type_id"] for rt in rel_types}

        col1, col2 = st.columns(2)
        source_id = entity_options[col1.selectbox("Source Entity *", list(entity_options.keys()))]
        target_id = entity_options[col2.selectbox("Target Entity *", list(entity_options.keys()))]
        type_id = rel_type_options[st.selectbox("Type *", list(rel_type_options.keys()))]
        description = st.text_area("Description")
        
        # --- DYNAMIC CUSTOM METADATA ---
        st.subheader("Custom Metadata")
        with db.get_connection() as conn:
            attr_defs = conn.execute(
                "SELECT * FROM attribute_definitions WHERE profile_id = ? AND target_table = 'relationships'",
                (profile_id,)
            ).fetchall()
        
        custom_attr_values = {}
        if attr_defs:
            for attr in attr_defs:
                custom_attr_values[attr["attribute_id"]] = st.text_input(f"{attr['name']} ({attr['data_type']})")
        
        if st.button("Save Relationship", type="primary"):
            if source_id == target_id: st.error("Source and Target must differ.")
            else:
                with db.get_connection() as conn:
                    new_id = db.save_relationship(conn, source_entity_id=source_id, target_entity_id=target_id, type_id=type_id, description=description)
                    # Save custom attributes
                    for attr_id, val in custom_attr_values.items():
                        if val.strip():
                            db.save_attribute_value(conn, attribute_id=attr_id, relationship_id=new_id, value_text=val.strip())
                st.success("Relationship saved."); st.rerun()

    with tab_view:
        if relationships:
            df = pd.DataFrame([dict(r) for r in relationships])
            st.dataframe(df[["relationship_id", "source_name", "relationship_type", "target_name"]], hide_index=True)

def page_comparative() -> None:
    st.header("Comparative Analysis")
    st.write("Select two or more documents to compare their statistics and entity frequencies side-by-side.")

    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if len(documents) < 2:
        st.warning("You need at least two documents imported to perform a comparison.")
        return

    doc_labels = _document_labels(documents)
    selected_labels = st.multiselect(
        "Select documents to compare",
        options=list(doc_labels.keys()),
        default=list(doc_labels.keys())[:2]
    )

    if len(selected_labels) < 2:
        st.info("Please select at least two documents.")
        return

    selected_ids = [doc_labels[label] for label in selected_labels]

    # --- 1. General Statistics Comparison ---
    st.subheader("1. Text Statistics")
    
    stats_data = []
    for label, doc_id in zip(selected_labels, selected_ids):
        with db.get_connection() as conn:
            doc = db.get_document(conn, doc_id)
            passages = _passage_rows_to_dicts(db.get_passages(conn, doc_id))
        
        stats = _cached_document_statistics(doc["source_text"], passages)
        stats_data.append({
            "Document": label.split(" — ")[1],
            "Words": stats["word_count"],
            "Unique Words": stats["unique_word_count"],
            "Passages": stats["passage_count"],
            "Sentences": stats["sentence_count"]
        })
    
    st.dataframe(pd.DataFrame(stats_data).set_index("Document").T, use_container_width=True)


    # --- 2. Entity Frequency Comparison ---
    st.subheader("2. Entity Mention Frequency Across Documents")
    st.caption("This table shows how many times each registered Entity was explicitly annotated (as a Mention) in each selected document.")

    placeholders = ",".join("?" for _ in selected_ids)
    query = f"""
        SELECT m.doc_id, e.canonical_name, e.entity_id, COUNT(m.mention_id) as count
        FROM mentions m
        JOIN entities e ON m.entity_id = e.entity_id
        WHERE m.doc_id IN ({placeholders})
        GROUP BY m.doc_id, e.entity_id
    """
    
    with db.get_connection() as conn:
        rows = conn.execute(query, selected_ids).fetchall()

    if not rows:
        st.info("No mentions have been registered in the selected documents yet. Use the AI Review or Mention Registration page to create some.")
    else:
        df = pd.DataFrame([dict(r) for r in rows])
        
        id_to_label = {v: k.split(" — ")[1] for k, v in doc_labels.items()}
        df["Document"] = df["doc_id"].map(id_to_label)
        
        pivot = df.pivot_table(
            index=["canonical_name", "entity_id"], 
            columns="Document", 
            values="count", 
            fill_value=0
        ).reset_index()
        
        pivot.columns.name = None
        doc_cols = [c for c in pivot.columns if c not in ["canonical_name", "entity_id"]]
        pivot["Total Mentions"] = pivot[doc_cols].sum(axis=1)
        pivot = pivot.sort_values("Total Mentions", ascending=False)

        st.dataframe(
            pivot.set_index(["canonical_name", "entity_id"]),
            use_container_width=True
        )

def page_ai_review() -> None:
    st.header("AI Candidate Review")
    st.write(
        "Review entities detected by the recognition engine. "
        "Accepted candidates will become verified Entities and Mentions."
    )

    with db.get_connection() as conn:
        documents = db.list_documents(conn)
        profiles = db.get_profiles(conn)

    if not documents:
        st.info("No documents imported yet.")
        return

    profile_id = profiles[0]["profile_id"] if profiles else 1
    doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
    selected_doc_label = st.selectbox("Select Document", list(doc_options.keys()))
    doc_id = doc_options[selected_doc_label]

    # Run Recognition
    if st.button("Run Entity Recognition", type="primary"):
        with st.spinner("Scanning text for candidates..."):
            with db.get_connection() as conn:
                count = ai_recognizer.recognize_candidates(conn, doc_id, profile_id)
        if count > 0:
            st.success(f"Found {count} new candidates.")
        else:
            st.info("No new candidates found.")

    st.divider()

    # Load Candidates
    with db.get_connection() as conn:
        candidates = db.get_candidates(conn, doc_id)
        categories = db.get_categories(conn, profile_id)

    if not candidates:
        st.info("No pending candidates for this document. Run recognition or check another document.")
        return

    cat_options = {c["name"]: c["category_id"] for c in categories}

    st.subheader(f"Pending Candidates ({len(candidates)})")
    
    # --- PAGINATION FOR PERFORMANCE ---
    # We only render 10 candidates at a time to prevent the browser from freezing
    REVIEW_PAGE_SIZE = 10
    total_pages = max(1, math.ceil(len(candidates) / REVIEW_PAGE_SIZE))
    
    col_page, col_info = st.columns([1, 3])
    page = col_page.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="review_page")
    offset = (int(page) - 1) * REVIEW_PAGE_SIZE
    
    col_info.write(f"Showing candidates {offset + 1} to {min(offset + REVIEW_PAGE_SIZE, len(candidates))} of {len(candidates)}")
    
    page_candidates = candidates[offset:offset + REVIEW_PAGE_SIZE]

    for c in page_candidates:
        with st.container(border=True):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown(f"**Surface Form:** `{c['surface_form']}`")
                st.caption(f"Passage {c['passage_id']} (Chars {c['char_start']}-{c['char_end']})")
                
                # Highlight the candidate in context
                context = c['passage_text']
                start, end = c['char_start'], c['char_end']
                highlighted = context[:start] + f"<mark>{context[start:end]}</mark>" + context[end:]
                st.markdown(highlighted, unsafe_allow_html=True)
                
                st.caption(f"*Method:* {c['recognition_method']} | *Confidence:* {c['confidence_score']}")

            with col2:
                st.write("**Suggested Category:**")
                default_idx = list(cat_options.keys()).index(c['suggested_category_name']) if c['suggested_category_name'] in cat_options else 0
                selected_cat_name = st.selectbox("Category", list(cat_options.keys()), index=default_idx, key=f"cat_{c['candidate_id']}")
                
                # Actions
                col_accept, col_reject = st.columns(2)
                if col_accept.button("✔ Accept", key=f"acc_{c['candidate_id']}", type="primary"):
                    with db.get_connection() as conn:
                        # 1. Create verified Entity
                        new_entity_id = db.save_entity(
                            conn, profile_id=profile_id, 
                            canonical_name=c['surface_form'], 
                            category_id=cat_options[selected_cat_name]
                        )
                        # 2. Create verified Mention
                        db.save_mention(
                            conn, entity_id=new_entity_id, doc_id=doc_id,
                            passage_id=c['passage_id'], surface_form=c['surface_form'],
                            char_start=c['char_start'], char_end=c['char_end']
                        )
                        # 3. Update Candidate status
                        db.update_candidate_status(conn, c['candidate_id'], 'accepted')
                    st.rerun()

                if col_reject.button("✘ Reject", key=f"rej_{c['candidate_id']}"):
                    with db.get_connection() as conn:
                        db.update_candidate_status(conn, c['candidate_id'], 'rejected')
                    st.rerun()
                    
def page_export() -> None:
    st.header("Export Data")
    with db.get_connection() as conn:
        documents = db.list_documents(conn)

    if not documents:
        st.info("No data to export yet.")
        return

    tab_data, tab_gephi, tab_qgis = st.tabs(["📄 Data (JSON & TEI)", "🕸️ Gephi", "🗺️ QGIS (GeoJSON)"])

    with tab_data:
        with db.get_connection() as conn:
            combined_json = exporter.generate_json_export(conn)
            st.download_button("Download JSON", data=combined_json.encode("utf-8"), file_name="textencode.json", mime="application/json")
        st.divider()
        doc_options = {f"{d['doc_id']} — {d['title']}": d["doc_id"] for d in documents}
        selected_doc_label = st.selectbox("Select a document to encode as TEI", list(doc_options.keys()))
        if st.button("Generate TEI XML"):
            with db.get_connection() as conn:
                xml_string = exporter.generate_tei_xml(conn, doc_options[selected_doc_label])
            st.download_button("Download TEI XML", data=xml_string.encode("utf-8"), file_name=f"textencode_tei.xml", mime="application/xml")

    with tab_gephi:
        scope_options = {"Whole Project": None}
        scope_options.update({f"Only: {d['doc_id']}": d["doc_id"] for d in documents})
        target_doc_id = scope_options[st.selectbox("Export Scope", list(scope_options.keys()))]
        if st.button("Generate Gephi Exports"):
            with db.get_connection() as conn:
                gexf_bytes, nodes_csv, edges_csv = exporter.generate_gephi_data(conn, target_doc_id)
            col1, col2, col3 = st.columns(3)
            col1.download_button("Download GEXF", data=gexf_bytes, file_name="network.gexf", mime="application/gexf+xml", use_container_width=True)
            col2.download_button("Download Nodes CSV", data=nodes_csv, file_name="nodes.csv", mime="text/csv", use_container_width=True)
            col3.download_button("Download Edges CSV", data=edges_csv, file_name="edges.csv", mime="text/csv", use_container_width=True)

    with tab_qgis:
        st.write("Export Entities that have latitude and longitude coordinates as a GeoJSON file.")
        if st.button("Generate QGIS GeoJSON", type="primary"):
            with db.get_connection() as conn:
                geojson_str = exporter.generate_qgis_geojson(conn)
            st.download_button("📥 Download GeoJSON", data=geojson_str.encode("utf-8"), file_name="textencode_map.geojson", mime="application/geo+json", use_container_width=True)

def page_settings() -> None:
    st.header("Settings")
    if Path(DB_FILE).exists():
        st.download_button("Download database backup", data=Path(DB_FILE).read_bytes(), file_name="backup.db")

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

PAGES = {
    "Dashboard": page_dashboard,
    "Import Documents": page_import,
    "Document Reader": page_reader,
    "Text Statistics": page_statistics,
    "Linguistic Analysis": page_linguistics,
    "Keyword Search": page_search,
    "Taxonomy Manager": taxonomy_ui.render_taxonomy_manager,  # <--- Added here
    "Entity Registration": page_entities,
    "Mention Registration": page_mentions,
    "Relationship Registration": page_relationships,
    "AI Candidate Review": page_ai_review,
    "Comparative Analysis": page_comparative,
    "Export Data": page_export,
    "Settings": page_settings,
}

with st.sidebar:
    st.markdown("### 📖 TextEncode v0.3")
    choice = st.radio("Navigation", list(PAGES))
    st.caption("Stage 1 · Taxonomy Infrastructure")

PAGES[choice]()