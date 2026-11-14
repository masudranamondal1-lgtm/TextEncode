# TextEncode Roadmap

## MVP (three-day assignment) — COMPLETED

- [x] Markdown import (UTF-8, multiple files, Bengali + English).
- [x] Structure-aware parsing (headings, paragraphs, list items, block quotes).
- [x] Stable document and passage IDs with character offsets.
- [x] Text statistics and keyword search.
- [x] SQLite database with 12 default entity categories and 16 relationship types.
- [x] Entity registration with alternative names.
- [x] Mention registration linked to passages.
- [x] Relationship registration with evidence passages.
- [x] JSON export (combined).
- [x] Basic TEI-compatible XML export.
- [x] CSV export of passages and text statistics.

## Known Limitations (to address in 2.0)
- **Tokenization:** Bengali word counts use whitespace splitting. Morphological variants (e.g., নদী and নদীর) are counted separately. Future versions will integrate a lightweight morphological lemmatizer.
- **TEI Validation:** The XML export is TEI-compatible but not strictly schema-validated against a custom ODD.
- **Mentions:** Mentions are currently passage-level, not character-level (no inline highlighting in the UI).

## TextEncode 2.0 — Research Platform

- Automatic entity recognition (NER) using Indic NLP models.
- Custom entity categories UI.
- Full TEI P5 validation against `tei_all.rng`.
- Document versioning and annotation reconciliation.
- Relationship-network visualisation (NetworkX).
- Text comparison across documents.
- GIS / geocoding for place entities.