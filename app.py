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
    cols[0].metric("Documents", stats["documents
