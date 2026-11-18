import sqlite3
from pathlib import Path
import importlib.util


def load_backup_function():
    # Exercise the exact function body copied from the patch script's source
    # by applying the patch to an isolated miniature repository.
    import subprocess
    import sys
    import tempfile

    project = Path(tempfile.mkdtemp())
    (project / "database").mkdir()
    (project / "database" / "db.py").write_text(
        'import sqlite3\nfrom datetime import datetime, timezone\nfrom pathlib import Path\n'
        'DB_PATH = Path(__file__).with_name("test.db")\n'
        'def utc_now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")\n',
        encoding="utf-8",
    )
    (project / "app.py").write_text(
        'from pathlib import Path\nimport streamlit as st\nfrom database import db\nDB_FILE = db.DB_PATH\n'
        'def page_dashboard():\n    st.caption(f"Database: {DB_FILE}")\n',
        encoding="utf-8",
    )
    script = Path(__file__).parents[1] / "apply_phase1_backup.py"
    subprocess.run([sys.executable, str(script)], cwd=project, check=True, capture_output=True, text=True)
    spec = importlib.util.spec_from_file_location("patched_db", project / "database" / "db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, project


def test_backup_contains_committed_data_and_passes_integrity_check():
    db, project = load_backup_function()
    source = project / "database" / "test.db"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO records(value) VALUES ('বাংলা গবেষণা')")

    backup = Path(db.create_safe_backup(source))
    assert backup.is_file()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM records").fetchone()[0] == "বাংলা গবেষণা"


def test_backup_missing_source_raises():
    db, project = load_backup_function()
    missing = project / "does-not-exist.db"
    try:
        db.create_safe_backup(missing)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError")
