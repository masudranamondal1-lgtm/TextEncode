# TextEncode Architecture (v0.5 Vision)

## Core Hierarchy
**Workspace → Research Project → Corpus → Documents → Annotations → Analysis → Research Outputs**

## Module Separation
*   `modules/text_analysis/`: Voyant-style statistics, KWIC, N-grams.
*   `modules/bengali_nlp/`: Tokenization, POS tagging, morphological analysis.
*   `modules/discovery/`: Seed-guided and Open Corpus discovery algorithms.
*   `modules/evidence/`: Management of Evidence Bundles (literary, historical, spatial).
*   `modules/interoperability/`: TEI, GEXF, GeoJSON, GraphML exports.

## UI Philosophy
Research-first. No generic AI dashboards. Clear evidence trails. Visual separation of verified vs. unverified data.
