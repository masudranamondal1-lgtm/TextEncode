# TextEncode

A local, general-purpose Markdown text processing, annotation and encoding
application for Digital Humanities research. Not tied to any single novel,
author or research project.

## Status

Stage 1 (Day 1): document import, passage identification, text statistics and
keyword search. Entity/mention/relationship registration (Stage 2) and
exports including TEI (Stage 3) follow.

## Requirements

- Python 3.10 or newer (3.11 recommended)
- Windows, macOS or Linux

## Installation (Windows PowerShell)

```powershell
cd TextEncode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
