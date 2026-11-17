# TextEncode Repository Audit (Phase 0)
**Date:** November 2026
**Current Version:** v0.4
**Architecture:** Streamlit, SQLite, Python

## 1. Existing Architecture
*   **Frontend:** Streamlit with multipage navigation (`st.navigation`). UI is broken into `app.py` (routing and page logic) and `ui/` (theme, components, network/spatial pages).
*   **Database:** SQLite with FTS5 search. Tables: `documents`, `passages`, `entities`, `mentions`, `relationships`, `taxonomy_profiles`.
*   **NLP Engine:** A custom, modular rule-based Bengali morphological engine (`modules/bengali_nlp/`) designed for speed and CPU compatibility.

## 2. Feature Status Matrix
| Feature | Status | Notes |
| :--- | :--- | :--- |
| Markdown/TXT Import | **Fully Implemented** | Fast parsing, exact offsets preserved. |
| Text Analysis (KWIC, N-grams) | **Fully Implemented** | Voyant-style exploration. |
| Entity/Relationship CRUD | **Fully Implemented** | Soft deletes and Trash implemented. |
| Network & Spatial Maps | **Fully Implemented** | `streamlit-agraph` and `st.map`. |
| Bengali NLP (Seed-guided) | **Partially Implemented** | Basic suffix stripping. Needs Paninian/contextual logic. |
| Evidence Bundles | **Not Implemented** | Currently, relationships only have a basic `description` and `evidence_passage_id`. |
| Workspace/Project Hierarchy | **Not Implemented** | Everything is currently flat under `documents`. |

## 3. Database Assessment
*   **Strengths:** Strong referential integrity (`ON DELETE CASCADE`), stable IDs.
*   **Weaknesses:** Lacks a hierarchical data model (Workspace -> Project -> Corpus -> Document). Lacks a dedicated table for storing structured **Evidence Bundles** (e.g., the difference between literary vs. historical evidence).

## 4. Technical Risks & Migration Requirements
*   **Risk:** Flattening the database structure too quickly will break existing annotations.
*   **Migration:** We must safely add `projects` and `corpora` tables, and attach existing `documents` to a default project.
