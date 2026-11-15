# TextEncode v0.3
**AI-Assisted Digital Humanities Annotation and Encoding Environment**

TextEncode is a local, general-purpose Markdown text processing and annotation platform. It handles large UTF-8 documents (100,000+ words) and transforms them into structured, machine-readable research data.

## Core Features (v0.3)
- **Extensible Taxonomy Manager:** Create custom entity categories, hierarchical subcategories, custom relationship types, and custom metadata fields.
- **AI Candidate Recognition:** A CPU-friendly heuristic engine scans texts for English proper nouns and Bengali morphological patterns (e.g., suffixes) to generate entity candidates.
- **Human-in-the-Loop Review:** Review, edit, accept, or reject AI candidates before they become verified data.
- **Character-Level Annotation:** Map verified Entities to exact Unicode character offsets. Mentions are visually highlighted in the Document Reader.
- **Bengali Linguistic Analysis:** A lightweight rule-based stemmer that groups morphological variants (e.g., নদী, নদীর) into a single lemma.
- **Interoperability:** 
  - **TEI P5:** Export standard XML with inline `<persName>` and `<placeName>` tags.
  - **Gephi:** Export Nodes/Edges (GEXF and CSV) for network analysis.
  - **QGIS:** Export Entities with coordinates as GeoJSON for spatial mapping.
- **Comparative Analysis:** A dashboard to compare text statistics and entity frequencies across multiple documents.
- **High-Performance Architecture:** SQLite FTS5 search and SQL-level pagination ensure smooth performance on large novels.

## Requirements
- Python 3.10 or newer (3.11 recommended)
- Windows, macOS, or Linux

## Installation (Windows PowerShell)
```powershell
cd path\to\TextEncode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt