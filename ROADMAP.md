# TextEncode Roadmap

## MVP (v0.1) — COMPLETED
- [x] Markdown import, parsing, and passage identification.
- [x] Basic text statistics and keyword search.
- [x] Entity, Mention, and Relationship registration.
- [x] SQLite persistence.
- [x] Basic JSON, CSV, and TEI XML export.

## Advanced Research Edition (v0.2) — COMPLETED
- [x] **Large Document Performance:** SQLite FTS5 search indexing and paginated UI rendering.
- [x] **Bengali Tokenization:** Lightweight rule-based morphological analysis (lemma grouping).
- [x] **Character-Level Annotation:** Exact Unicode offset mapping with inline HTML highlighting in the reader.
- [x] **Gephi Integration:** GEXF, Nodes CSV, and Edges CSV export for network analysis.
- [x] **QGIS Integration:** Spatial metadata fields (Lat/Lon) and GeoJSON export for GIS analysis.
- [x] **Comparative Analysis:** Multi-document statistics and entity frequency dashboard.

## TextEncode 3.0 — Future Vision
- [ ] Full NLP morphological analysis using transformer models (e.g., BanglaBERT).
- [ ] Full TEI P5 validation against custom ODD schemas.
- [ ] Native map visualizations and network graphs embedded directly in the Streamlit UI.
- [ ] Multi-user support with cloud database synchronization.
- [ ] Advanced OCR pipeline for PDF ingestion.