"""Small stdlib SQLite persistence layer. Submitted ingredient text is never stored."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parents[2] / "data" / "nutrisnap.db"

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ingredient(id TEXT PRIMARY KEY, canonical TEXT NOT NULL, category TEXT, primary_flag TEXT, verified INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ingredient_alias(id INTEGER PRIMARY KEY, ingredient_id TEXT NOT NULL REFERENCES ingredient(id), alias TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('name','ins')), UNIQUE(ingredient_id,alias));
CREATE TABLE IF NOT EXISTS flag_rule(flag TEXT PRIMARY KEY, penalty REAL NOT NULL, position_weighted INTEGER NOT NULL, is_bonus INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS scan(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, score INTEGER NOT NULL, band TEXT NOT NULL, scoring_method TEXT NOT NULL, fallback_reason TEXT, nova_top INTEGER, nova_confidence REAL, rule_score INTEGER, ml_score INTEGER, kb_coverage REAL NOT NULL, n_tokens INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS scan_ingredient(id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE, position INTEGER NOT NULL, raw_name TEXT NOT NULL, ingredient_id TEXT REFERENCES ingredient(id), flag TEXT, points REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ingredient_info(name_norm TEXT PRIMARY KEY, what_it_is TEXT NOT NULL, health_note TEXT NOT NULL, concern_level TEXT NOT NULL CHECK(concern_level IN ('none','low','medium','high')), source TEXT NOT NULL CHECK(source IN ('owner','gemini')), model TEXT, generated_at TEXT NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alternative_cache(cache_key TEXT PRIMARY KEY, content_json TEXT NOT NULL, source TEXT NOT NULL, model TEXT, generated_at TEXT NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ingredient_info(name_norm TEXT PRIMARY KEY, what_it_is TEXT NOT NULL, health_note TEXT NOT NULL, concern_level TEXT NOT NULL CHECK(concern_level IN ('none','low','medium','high')), source TEXT NOT NULL CHECK(source IN ('owner','gemini')), model TEXT, generated_at TEXT NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alternative_cache(cache_key TEXT PRIMARY KEY, content_json TEXT NOT NULL, source TEXT NOT NULL, model TEXT, generated_at TEXT NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_scan_created ON scan(created_at);
CREATE INDEX IF NOT EXISTS idx_scan_band ON scan(band);
CREATE INDEX IF NOT EXISTS idx_scan_method_reason ON scan(scoring_method,fallback_reason);
CREATE INDEX IF NOT EXISTS idx_scan_ing_scan ON scan_ingredient(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_ing_ingredient ON scan_ingredient(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_scan_ing_flag ON scan_ingredient(flag);
"""

def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def session(path: Path | str = DB_PATH):
    db = connect(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize(path: Path | str = DB_PATH) -> None:
    with session(path) as db:
        db.executescript(SCHEMA)

def seed(kb: Any, path: Path | str = DB_PATH) -> None:
    initialize(path)
    with session(path) as db:
        for key, entry in kb.entries.items():
            db.execute("INSERT OR IGNORE INTO ingredient VALUES(?,?,?,?,?)", (key, entry.get("canonical", key), entry.get("category"), entry.get("primary_flag"), int(bool(entry.get("verified")))))
            aliases = [(a, "name") for a in [entry.get("canonical", ""), *entry.get("aliases", [])] if a]
            aliases.extend((str(i), "ins") for i in entry.get("ins", []))
            for alias, kind in aliases:
                db.execute("INSERT OR IGNORE INTO ingredient_alias(ingredient_id,alias,kind) VALUES(?,?,?)", (key, alias, kind))
        rules = kb.rules
        for flag, row in rules.get("flags", {}).items():
            db.execute("INSERT OR REPLACE INTO flag_rule VALUES(?,?,?,0)", (flag, row.get("penalty", 0), int(bool(row.get("position_weighted")))))
        for flag, penalty in rules.get("bonus", {}).items():
            if flag != "cap":
                db.execute("INSERT OR REPLACE INTO flag_rule VALUES(?,?,0,1)", (flag, penalty))

def record_scan(result: Any, tokens: list[Any], path: Path | str = DB_PATH) -> None:
    if result.status != "ok" or result.score is None:
        return
    try:
        with session(path) as db:
            nova = result.nova
            cur = db.execute("INSERT INTO scan(created_at,score,band,scoring_method,fallback_reason,nova_top,nova_confidence,rule_score,ml_score,kb_coverage,n_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), result.score, result.band, result.scoring_method, result.fallback_reason, nova.top if nova else None, nova.confidence if nova else None, result.rule_score, result.ml_score, result.kb_coverage or 0, len(tokens)))
            scan_id = cur.lastrowid
            for ing in result.ingredients:
                db.execute("INSERT INTO scan_ingredient(scan_id,position,raw_name,ingredient_id,flag,points) VALUES(?,?,?,?,?,?)", (scan_id, ing.position, ing.name, ing.kb_id if ing.matched else None, ing.flag, ing.points))
    except (sqlite3.Error, OSError):
        # Persistence is best effort; scoring and the HTTP response remain available.
        return

def history(limit: int = 50, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with session(path) as db:
        return [dict(row) for row in db.execute("SELECT id,created_at,score,band,scoring_method,fallback_reason,kb_coverage,n_tokens FROM scan ORDER BY id DESC LIMIT ?", (max(1,min(limit,100)),))]

def stats(path: Path | str = DB_PATH) -> dict[str, Any]:
    with session(path) as db:
        return {"scans": db.execute("SELECT count(*) FROM scan").fetchone()[0], "ingredients": db.execute("SELECT count(*) FROM ingredient").fetchone()[0], "aliases": db.execute("SELECT count(*) FROM ingredient_alias").fetchone()[0], "flag_rules": db.execute("SELECT count(*) FROM flag_rule").fetchone()[0]}

def demo_queries(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    sql_path = Path(__file__).parents[2] / ".." / "docs" / "QUERIES.sql"
    content = sql_path.resolve().read_text(encoding="utf-8")
    with session(path) as db:
        output = []
        for chunk in content.split("-- QUERY:")[1:]:
            title, sql = chunk.split("\n", 1)
            output.append({"title": title.strip(), "rows": [dict(row) for row in db.execute(sql.strip())]})
        return output

def normalize_cache_name(name: str) -> str:
    return " ".join(name.casefold().split())

def cached_ingredient_info(names: list[str], path: Path | str = DB_PATH) -> dict[str, dict[str, Any]]:
    keys = sorted({normalize_cache_name(n) for n in names if n.strip()})
    if not keys:
        return {}
    with session(path) as db:
        placeholders = ",".join("?" for _ in keys)
        rows = db.execute(f"SELECT * FROM ingredient_info WHERE name_norm IN ({placeholders})", keys).fetchall()
        for row in rows:
            db.execute("UPDATE ingredient_info SET hit_count=hit_count+1 WHERE name_norm=?", (row["name_norm"],))
        return {row["name_norm"]: dict(row) for row in rows}

def save_ingredient_info(rows: list[dict[str, Any]], model: str, path: Path | str = DB_PATH) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with session(path) as db:
        for row in rows:
            db.execute("INSERT INTO ingredient_info(name_norm,what_it_is,health_note,concern_level,source,model,generated_at,verified) VALUES(?,?,?,?, 'gemini',?,?,0) ON CONFLICT(name_norm) DO NOTHING", (normalize_cache_name(row["name"]), row["what_it_is"], row["health_note"], row["concern_level"], model, now))

def cached_alternatives(cache_key: str, path: Path | str = DB_PATH) -> dict[str, Any] | None:
    with session(path) as db:
        row = db.execute("SELECT * FROM alternative_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        db.execute("UPDATE alternative_cache SET hit_count=hit_count+1 WHERE cache_key=?", (cache_key,))
        return dict(row)

def save_alternatives(cache_key: str, alternatives: list[dict[str, Any]], model: str, path: Path | str = DB_PATH) -> None:
    with session(path) as db:
        db.execute("INSERT INTO alternative_cache(cache_key,content_json,source,model,generated_at,verified) VALUES(?,?, 'gemini',?,?,0) ON CONFLICT(cache_key) DO NOTHING", (cache_key, json.dumps(alternatives, ensure_ascii=False), model, datetime.now(timezone.utc).isoformat()))

def normalize_cache_name(name: str) -> str:
    return " ".join(name.casefold().split())

def cached_ingredient_info(names: list[str], path: Path | str = DB_PATH) -> dict[str, dict[str, Any]]:
    keys = sorted({normalize_cache_name(n) for n in names if n.strip()})
    if not keys:
        return {}
    with session(path) as db:
        placeholders = ",".join("?" for _ in keys)
        rows = db.execute(f"SELECT * FROM ingredient_info WHERE name_norm IN ({placeholders})", keys).fetchall()
        for row in rows:
            db.execute("UPDATE ingredient_info SET hit_count=hit_count+1 WHERE name_norm=?", (row["name_norm"],))
        return {row["name_norm"]: dict(row) for row in rows}

def save_ingredient_info(rows: list[dict[str, Any]], model: str, path: Path | str = DB_PATH) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with session(path) as db:
        for row in rows:
            db.execute("INSERT INTO ingredient_info(name_norm,what_it_is,health_note,concern_level,source,model,generated_at,verified) VALUES(?,?,?,?, 'gemini',?,?,0) ON CONFLICT(name_norm) DO NOTHING", (normalize_cache_name(row["name"]), row["what_it_is"], row["health_note"], row["concern_level"], model, now))

def cached_alternatives(cache_key: str, path: Path | str = DB_PATH) -> dict[str, Any] | None:
    with session(path) as db:
        row = db.execute("SELECT * FROM alternative_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        db.execute("UPDATE alternative_cache SET hit_count=hit_count+1 WHERE cache_key=?", (cache_key,))
        return dict(row)

def save_alternatives(cache_key: str, alternatives: list[dict[str, Any]], model: str, path: Path | str = DB_PATH) -> None:
    with session(path) as db:
        db.execute("INSERT INTO alternative_cache(cache_key,content_json,source,model,generated_at,verified) VALUES(?,?, 'gemini',?,?,0) ON CONFLICT(cache_key) DO NOTHING", (cache_key, json.dumps(alternatives, ensure_ascii=False), model, datetime.now(timezone.utc).isoformat()))
