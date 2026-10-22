import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.core.database import connect, demo_queries, history, initialize, record_scan, seed, stats
from app.core.knowledge_base import KnowledgeBase
from app.core.scoring import analyze
from app.core.parser import parse


def db_path():
    path = Path(__file__).parents[1] / "data" / f"test-{uuid4().hex}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_seed_and_queries_are_idempotent():
    path = db_path()
    kb = KnowledgeBase()
    kb.load()
    seed(kb, path)
    seed(kb, path)
    counts = stats(path)
    assert counts["ingredients"] == len(kb.entries)
    assert counts["aliases"] > counts["ingredients"]
    assert len(demo_queries(path)) == 16
    path.unlink(missing_ok=True)


def test_scan_persistence_excludes_pasted_text():
    path = db_path()
    kb = KnowledgeBase()
    kb.load()
    seed(kb, path)
    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    result = analyze(text, kb=kb)
    record_scan(result, parse(text), path)
    rows = history(path=path)
    assert len(rows) == 1
    assert rows[0]["fallback_reason"] == "ml_disabled"
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        dump = " ".join(str(row) for row in db.execute("SELECT * FROM scan_ingredient"))
        assert text not in dump
        assert "sugar" in dump
    path.unlink(missing_ok=True)


def test_foreign_keys_and_cascade():
    path = db_path()
    initialize(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO scan(id,created_at,score,band,scoring_method,fallback_reason,nova_top,nova_confidence,rule_score,ml_score,kb_coverage,n_tokens,source) VALUES(1,'now',50,'Moderate Risk','rule_based','ml_disabled',NULL,NULL,50,NULL,.5,2,'paste')")
        db.execute("INSERT INTO scan_ingredient(scan_id,position,raw_name,points) VALUES(1,1,'salt',-2)")
        db.execute("DELETE FROM scan WHERE id=1")
        assert db.execute("SELECT count(*) FROM scan_ingredient").fetchone()[0] == 0
    path.unlink(missing_ok=True)


def test_wal_privacy_and_ist_history():
    path = db_path()
    kb = KnowledgeBase()
    kb.load()
    seed(kb, path)
    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    result = analyze(text, kb=kb)
    result.detected_text = text
    record_scan(result, parse(text), path, source="camera")
    rows = history(path=path)
    assert rows[0]["source"] == "camera"
    assert rows[0]["created_at_local"]
    assert "detected_text" not in rows[0]["result"]
    import json
    assert text not in json.dumps(rows[0]["result"])
    from contextlib import closing
    with closing(connect(path)) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.execute("SELECT user_id FROM scan").fetchone()[0] is None
    path.unlink(missing_ok=True)


def test_initialize_migrates_previous_scan_table():
    import sqlite3
    path = db_path()
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE scan(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,score INTEGER NOT NULL,band TEXT NOT NULL,scoring_method TEXT NOT NULL,fallback_reason TEXT,nova_top INTEGER,nova_confidence REAL,rule_score INTEGER,ml_score INTEGER,kb_coverage REAL NOT NULL,n_tokens INTEGER NOT NULL)")
    initialize(path)
    with closing(connect(path)) as db:
        cols = {row["name"] for row in db.execute("PRAGMA table_info(scan)")}
        assert {"source", "result_json", "user_id"}.issubset(cols)
    path.unlink(missing_ok=True)
