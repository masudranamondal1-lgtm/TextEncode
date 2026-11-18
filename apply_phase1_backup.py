"""Apply the TextEncode Phase 1 safe-backup patch in the repository root.

Usage: python apply_phase1_backup.py
The script is idempotent and refuses to edit files if expected anchors are absent.
"""
from pathlib import Path

ROOT = Path.cwd()
DB_FILE = ROOT / "database" / "db.py"
APP_FILE = ROOT / "app.py"

DB_FUNCTION = '''\n\ndef create_safe_backup(db_path: str | Path | None = None) -> str:
    """Create and verify a consistent SQLite backup, including committed WAL data.

    SQLite's online backup API provides a consistent snapshot while the source
    database is in use. The backup is written beside the source database.
    """
    source_path = Path(db_path) if db_path is not None else DB_PATH
    if not source_path.is_file():
        raise FileNotFoundError(f"Database file not found: {source_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = source_path.parent / f"{source_path.stem}_backup_{timestamp}{source_path.suffix or '.db'}"

    source = None
    destination = None
    try:
        source = sqlite3.connect(str(source_path), timeout=30)
        destination = sqlite3.connect(str(backup_path), timeout=30)
        source.backup(destination)
        check = destination.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise sqlite3.DatabaseError(f"Backup integrity check failed: {check[0] if check else 'no result'}")
        destination.commit()
    except Exception:
        if destination is not None:
            destination.close()
            destination = None
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()

    return str(backup_path)
'''

APP_UI = '''\n\n    st.divider()
    st.subheader("Data Management")
    st.caption("Create a consistent backup of the research database. The backup includes committed changes in SQLite WAL mode.")

    if st.button("Create Safe Database Backup", type="primary", key="create_safe_database_backup"):
        try:
            with st.spinner("Creating and verifying database backup..."):
                backup_file = db.create_safe_backup()
            st.session_state["textencode_latest_backup"] = backup_file
            st.success("Database backup created and integrity-checked.")
        except Exception as exc:
            st.error(f"Backup failed: {exc}")

    latest_backup = st.session_state.get("textencode_latest_backup")
    if latest_backup and Path(latest_backup).is_file():
        backup_path = Path(latest_backup)
        st.caption(f"Backup file: {backup_path.name}")
        st.download_button(
            "Download Database Backup",
            data=backup_path.read_bytes(),
            file_name=backup_path.name,
            mime="application/x-sqlite3",
            key="download_latest_database_backup",
        )
'''

if not DB_FILE.is_file() or not APP_FILE.is_file():
    raise SystemExit("Run this script from the TextEncode repository root (app.py and database/db.py required).")

db_text = DB_FILE.read_text(encoding="utf-8-sig")
app_text = APP_FILE.read_text(encoding="utf-8-sig")

if "def create_safe_backup(" not in db_text:
    anchor = "def utc_now() -> str: return datetime.now(timezone.utc).isoformat(timespec=\"seconds\")"
    if anchor not in db_text:
        raise SystemExit("Could not find the expected utc_now() anchor in database/db.py; no files changed.")
    db_text = db_text.replace(anchor, anchor + DB_FUNCTION, 1)

if 'key="create_safe_database_backup"' not in app_text:
    anchor = '    st.caption(f"Database: {DB_FILE}")'
    if anchor not in app_text:
        raise SystemExit("Could not find the expected database caption in app.py; no files changed.")
    app_text = app_text.replace(anchor, anchor + APP_UI, 1)

# Write only after both files have passed their anchor checks.
DB_FILE.write_text(db_text, encoding="utf-8")
APP_FILE.write_text(app_text, encoding="utf-8")
print("Phase 1 safe-backup feature applied to app.py and database/db.py.")
print("Next: run python -m py_compile app.py database/db.py and pytest.")
