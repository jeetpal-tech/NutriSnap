import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.core.database import demo_queries, history, initialize, record_scan, seed, stats
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
    assert len(demo_queries(path)) == 12
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
        db.execute("INSERT INTO scan VALUES(1,'now',50,'Moderate Risk','rule_based','ml_disabled',NULL,NULL,50,NULL,.5,2)")
        db.execute("INSERT INTO scan_ingredient(scan_id,position,raw_name,points) VALUES(1,1,'salt',-2)")
        db.execute("DELETE FROM scan WHERE id=1")
        assert db.execute("SELECT count(*) FROM scan_ingredient").fetchone()[0] == 0
    path.unlink(missing_ok=True)
