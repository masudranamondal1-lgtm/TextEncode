TextEncode v0.3.1
**Visual Design Refinement & Research Workstation Edition**

TextEncode is a local, general-purpose Digital Humanities application for processing, annotating, organizing, and encoding textual documents. Designed to handle large Bengali and English texts (100,000+ words), it transforms raw Markdown into structured, machine-readable research data.

## Major Features (v0.3.1)
- **Scholarly Interface:** Fully redesigned UI featuring editorial typography (Source Serif 4, Inter, Noto Serif Bengali).
- **4 Display Modes:** Classic Light, Dark Research, Eye Comfort, and High Contrast.
- **Reading Preferences:** Fully adjustable font size, line spacing, and reading width for long-form reading.
- **Bengali NLP Engine:** Modular rule-based morphological analyzer (nouns, verbs, compound analysis) with human-in-the-loop AI review.
- **Interoperability:** Export to TEI P5 XML, Gephi (GEXF), QGIS (GeoJSON), and JSON/CSV.
- **Extensible Taxonomy:** Custom categories, relationship types, and metadata attributes.
- **Performance:** SQLite FTS5 search and SQL-level pagination for large documents.

## Installation (Windows PowerShell)
```powershell
cd path\to\TextEncode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt