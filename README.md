# TextEncode

A local, general-purpose Markdown text processing, annotation and encoding application for Digital Humanities research. It is designed to handle UTF-8 Markdown files in Bengali and English.

## Features (MVP)
- **Import:** Upload Markdown files. The original source text is preserved exactly.
- **Parse:** Automatically identifies headings, paragraphs, list items, and block quotes with Unicode character offsets.
- **Statistics:** Word counts, sentence counts, and frequency analysis (approx.).
- **Annotate:** Register Entities (12 default categories), link them to specific passages as Mentions, and register Relationships between Entities with evidence.
- **Export:** Download your dataset as JSON, or export documents as basic TEI P5 XML.

## Requirements
- Python 3.10 or newer (3.11 recommended)
- Windows, macOS or Linux

## Installation (Windows PowerShell)

```powershell
# 1. Create the project and virtual environment
cd path\to\TextEncode
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt