import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_db_module():
    spec = importlib.util.spec_from_file_location('phase3_db_under_test', ROOT / 'database' / 'db.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_migration_and_evidence_metadata(tmp_path):
    db = load_db_module()
    path = tmp_path / 'phase3.sqlite'
    db.init_db(path)
    with db.get_connection(path) as conn:
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(evidence_bundles)')}
        expected = {'source_type','source_identifier','author','source_title','publisher','publication_year','page_reference','url','access_date','verification_status','researcher_note'}
        assert expected <= cols
        profile = conn.execute('SELECT profile_id FROM taxonomy_profiles LIMIT 1').fetchone()[0]
        category = conn.execute('SELECT category_id FROM entity_categories WHERE profile_id=? LIMIT 1',(profile,)).fetchone()[0]
        type_id = conn.execute('SELECT type_id FROM relationship_types WHERE profile_id=? LIMIT 1',(profile,)).fetchone()[0]
        now = db.utc_now()
        conn.execute("INSERT INTO entities(entity_id,profile_id,canonical_name,category_id,created_at) VALUES('E1',?,?,?,?)",(profile,'River',category,now))
        conn.execute("INSERT INTO entities(entity_id,profile_id,canonical_name,category_id,created_at) VALUES('E2',?,?,?,?)",(profile,'Community',category,now))
        conn.execute("INSERT INTO relationships(relationship_id,source_entity_id,target_entity_id,type_id,created_at) VALUES('R1','E1','E2',?,?)",(type_id,now))
        evidence_id = db.add_evidence_bundle(conn,'R1','Literary','A quoted passage','Chapter 2',source_type='Book',author='A. Author',source_title='A River Text',publication_year=1998,page_reference='p. 42',verification_status='checked')
        row = conn.execute('SELECT * FROM evidence_bundles WHERE evidence_id=?',(evidence_id,)).fetchone()
        assert row['author'] == 'A. Author'
        assert row['publication_year'] == 1998
        assert row['verification_status'] == 'checked'


def test_invalid_verification_status_rejected(tmp_path):
    db = load_db_module()
    path = tmp_path / 'invalid.sqlite'
    db.init_db(path)
    with db.get_connection(path) as conn:
        try:
            db.add_evidence_bundle(conn,'missing','Literary','text',verification_status='approved-ish')
        except ValueError as exc:
            assert 'Invalid verification status' in str(exc)
        else:
            raise AssertionError('Invalid status should be rejected')
