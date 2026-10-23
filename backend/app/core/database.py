"""Transactional SQLite persistence for scan lifecycles and reusable notes.

SQLite remains the deliberate single-node choice for the demo.  The public API
uses the opaque ``public_id`` and an anonymous server-issued session; the
integer primary key is retained as a private join key for compatibility with
the existing database and local SQL demonstrations.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

DB_PATH = Path(__file__).parents[2] / "data" / "nutrisnap.db"
SCHEMA_VERSION = 2
CACHE_SCHEMA_VERSION = 1

LIFECYCLE_STATUSES = {
    "received",
    "extracting",
    "awaiting_confirmation",
    "analyzing",
    "completed",
    "completed_limited",
    "failed",
    "cancelled",
    "interrupted",
}
_TERMINAL_STATUSES = {"completed", "completed_limited", "failed", "cancelled", "interrupted"}
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "received": {"extracting", "analyzing", "failed", "cancelled", "interrupted"},
    "extracting": {"awaiting_confirmation", "analyzing", "failed", "cancelled", "interrupted"},
    "awaiting_confirmation": {"analyzing", "failed", "cancelled", "interrupted"},
    "analyzing": {"completed", "completed_limited", "failed", "cancelled", "interrupted"},
    "completed": set(),
    "completed_limited": set(),
    "failed": set(),
    "cancelled": set(),
    "interrupted": set(),
}

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredient(
    id TEXT PRIMARY KEY,
    canonical TEXT NOT NULL,
    category TEXT,
    primary_flag TEXT,
    verified INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredient_alias(
    id INTEGER PRIMARY KEY,
    ingredient_id TEXT NOT NULL REFERENCES ingredient(id),
    alias TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('name','ins')),
    UNIQUE(ingredient_id,alias)
);
CREATE TABLE IF NOT EXISTS flag_rule(
    flag TEXT PRIMARY KEY,
    penalty REAL NOT NULL,
    position_weighted INTEGER NOT NULL,
    is_bonus INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scan(
    id INTEGER PRIMARY KEY,
    public_id TEXT,
    session_id TEXT,
    idempotency_key TEXT,
    request_id TEXT,
    request_fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    completed_at TEXT,
    score INTEGER,
    band TEXT,
    scoring_method TEXT,
    fallback_reason TEXT,
    nova_top INTEGER,
    nova_confidence REAL,
    rule_score INTEGER,
    ml_score INTEGER,
    kb_coverage REAL NOT NULL DEFAULT 0,
    n_tokens INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'paste' CHECK(source IN ('camera','upload','paste')),
    completeness TEXT NOT NULL DEFAULT 'complete',
    result_schema_version INTEGER NOT NULL DEFAULT 1,
    scoring_version INTEGER NOT NULL DEFAULT 1,
    kb_version INTEGER NOT NULL DEFAULT 0,
    parent_scan_id INTEGER REFERENCES scan(id),
    revision INTEGER NOT NULL DEFAULT 1,
    result_json TEXT,
    user_id INTEGER NULL,
    CHECK(status IN ('received','extracting','awaiting_confirmation','analyzing','completed','completed_limited','failed','cancelled','interrupted'))
);
CREATE TABLE IF NOT EXISTS scan_ingredient(
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT,
    ingredient_id TEXT REFERENCES ingredient(id),
    flag TEXT,
    points REAL NOT NULL,
    assessment_state TEXT NOT NULL DEFAULT 'unknown',
    provenance TEXT
);
CREATE TABLE IF NOT EXISTS provider_attempt(
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    attempted INTEGER NOT NULL DEFAULT 1,
    attempt_number INTEGER NOT NULL,
    model TEXT,
    outcome TEXT NOT NULL,
    status_code INTEGER,
    duration_ms INTEGER,
    fallback_category TEXT,
    usage_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingredient_info(
    name_norm TEXT PRIMARY KEY,
    what_it_is TEXT NOT NULL,
    health_note TEXT NOT NULL,
    concern_level TEXT NOT NULL CHECK(concern_level IN ('none','low','medium','high')),
    source TEXT NOT NULL CHECK(source IN ('owner','gemini')),
    model TEXT,
    generated_at TEXT NOT NULL,
    expires_at TEXT,
    prompt_version TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    hit_count INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alternative_cache(
    cache_key TEXT PRIMARY KEY,
    content_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('owner','gemini')),
    model TEXT,
    generated_at TEXT NOT NULL,
    expires_at TEXT,
    prompt_version TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    hit_count INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_SCAN = """
CREATE TABLE IF NOT EXISTS scan(
    id INTEGER PRIMARY KEY,
    public_id TEXT,
    session_id TEXT,
    idempotency_key TEXT,
    request_id TEXT,
    request_fingerprint TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    completed_at TEXT,
    score INTEGER,
    band TEXT,
    scoring_method TEXT,
    fallback_reason TEXT,
    nova_top INTEGER,
    nova_confidence REAL,
    rule_score INTEGER,
    ml_score INTEGER,
    kb_coverage REAL NOT NULL DEFAULT 0,
    n_tokens INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'paste' CHECK(source IN ('camera','upload','paste')),
    completeness TEXT NOT NULL DEFAULT 'complete',
    result_schema_version INTEGER NOT NULL DEFAULT 1,
    scoring_version INTEGER NOT NULL DEFAULT 1,
    kb_version INTEGER NOT NULL DEFAULT 0,
    parent_scan_id INTEGER REFERENCES scan(id),
    revision INTEGER NOT NULL DEFAULT 1,
    result_json TEXT,
    user_id INTEGER NULL,
    CHECK(status IN ('received','extracting','awaiting_confirmation','analyzing','completed','completed_limited','failed','cancelled','interrupted'))
)
"""
_CREATE_SCAN_INGREDIENT = """
CREATE TABLE IF NOT EXISTS scan_ingredient(
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT,
    ingredient_id TEXT REFERENCES ingredient(id),
    flag TEXT,
    points REAL NOT NULL,
    assessment_state TEXT NOT NULL DEFAULT 'unknown',
    provenance TEXT
)
"""
_CREATE_PROVIDER_ATTEMPT = """
CREATE TABLE IF NOT EXISTS provider_attempt(
    id INTEGER PRIMARY KEY,
    scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    attempted INTEGER NOT NULL DEFAULT 1,
    attempt_number INTEGER NOT NULL,
    model TEXT,
    outcome TEXT NOT NULL,
    status_code INTEGER,
    duration_ms INTEGER,
    fallback_category TEXT,
    usage_json TEXT,
    created_at TEXT NOT NULL
)
"""


class PersistenceError(RuntimeError):
    """Raised when an accepted scan cannot be durably written."""


class IdempotencyConflict(PersistenceError):
    """The same owner/key was reused with a different request payload."""


class ScanInProgress(PersistenceError):
    """An identical idempotent request is already being processed."""

    def __init__(self, message: str, scan: sqlite3.Row | None = None) -> None:
        super().__init__(message)
        self.scan = scan


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def session(path: Path | str = DB_PATH):
    db = connect(path)
    try:
        db.execute("BEGIN")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _add_column_if_missing(db: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _rebuild_legacy_scan_tables(db: sqlite3.Connection) -> None:
    """Upgrade the original NOT NULL-score/CHECK(source) table in place."""
    scan_info = list(db.execute("PRAGMA table_info(scan)"))
    if not scan_info:
        return
    columns = {row["name"]: row for row in scan_info}
    if "status" in columns and ("score" not in columns or columns["score"]["notnull"] == 0):
        return

    child_exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scan_ingredient'").fetchone())
    if child_exists:
        db.execute("ALTER TABLE scan_ingredient RENAME TO scan_ingredient_legacy")
    db.execute("ALTER TABLE scan RENAME TO scan_legacy")
    db.execute(_CREATE_SCAN)
    db.execute(_CREATE_SCAN_INGREDIENT)

    def old(name: str, fallback: str) -> str:
        return name if name in columns else fallback

    created_col = old("created_at", "''")
    source_col = old("source", "'paste'")
    db.execute(
        f"INSERT INTO scan(id,created_at,score,band,scoring_method,fallback_reason,nova_top,nova_confidence,rule_score,ml_score,kb_coverage,n_tokens,source,result_json,user_id,status,updated_at,completeness) "
        f"SELECT id,{created_col},{old('score', 'NULL')},{old('band', 'NULL')},{old('scoring_method', 'NULL')},{old('fallback_reason', 'NULL')},{old('nova_top', 'NULL')},{old('nova_confidence', 'NULL')},{old('rule_score', 'NULL')},{old('ml_score', 'NULL')},{old('kb_coverage', '0')},{old('n_tokens', '0')},{source_col},{old('result_json', 'NULL')},{old('user_id', 'NULL')},'completed',{created_col},'complete' FROM scan_legacy"
    )
    if child_exists:
        legacy_child_columns = {row["name"] for row in db.execute("PRAGMA table_info(scan_ingredient_legacy)")}
        def child_old(name: str, fallback: str) -> str:
            return name if name in legacy_child_columns else fallback
        db.execute(
            f"INSERT INTO scan_ingredient(id,scan_id,position,raw_name,ingredient_id,flag,points) "
            f"SELECT id,scan_id,position,raw_name,{child_old('ingredient_id', 'NULL')},{child_old('flag', 'NULL')},{child_old('points', '0')} FROM scan_ingredient_legacy"
        )
        db.execute("DROP TABLE scan_ingredient_legacy")
        db.execute("DROP TABLE scan_legacy")


def _repair_provider_attempt_foreign_key(db: sqlite3.Connection) -> None:
    """Repair databases migrated before provider_attempt was introduced.

    SQLite rewrites foreign-key references when a legacy scan table is renamed.
    If provider_attempt already existed during that migration, its constraint
    can incorrectly retain ``scan_legacy`` as the parent table. Rebuild only
    that small table, preserving every provider-attempt row.
    """
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='provider_attempt'"
    ).fetchone()
    sql = str(row[0] or "") if row else ""
    if "scan_legacy" not in sql:
        return

    db.execute("ALTER TABLE provider_attempt RENAME TO provider_attempt_legacy_fk")
    db.execute(_CREATE_PROVIDER_ATTEMPT)
    db.execute(
        "INSERT INTO provider_attempt(id,scan_id,operation,attempted,attempt_number,model,outcome,status_code,duration_ms,fallback_category,usage_json,created_at) "
        "SELECT id,scan_id,operation,attempted,attempt_number,model,outcome,status_code,duration_ms,fallback_category,usage_json,created_at "
        "FROM provider_attempt_legacy_fk"
    )
    db.execute("DROP TABLE provider_attempt_legacy_fk")


def initialize(path: Path | str = DB_PATH) -> None:
    """Create or upgrade the local schema without deleting existing records."""
    with session(path) as db:
        _rebuild_legacy_scan_tables(db)
        db.executescript(SCHEMA)
        _repair_provider_attempt_foreign_key(db)

        # The original Release 1 schema predates lifecycle ownership.  Keep all
        # rows and add compatible columns with safe defaults.
        migrations = {
            "source": "TEXT NOT NULL DEFAULT 'paste'",
            "result_json": "TEXT",
            "user_id": "INTEGER NULL",
            "public_id": "TEXT",
            "session_id": "TEXT",
            "idempotency_key": "TEXT",
            "request_id": "TEXT",
            "request_fingerprint": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'completed'",
            "updated_at": "TEXT",
            "completed_at": "TEXT",
            "completeness": "TEXT NOT NULL DEFAULT 'complete'",
            "result_schema_version": "INTEGER NOT NULL DEFAULT 1",
            "scoring_version": "INTEGER NOT NULL DEFAULT 1",
            "kb_version": "INTEGER NOT NULL DEFAULT 0",
            "parent_scan_id": "INTEGER",
            "revision": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, ddl in migrations.items():
            _add_column_if_missing(db, "scan", name, ddl)
        for name, ddl in {
            "normalized_name": "TEXT",
            "assessment_state": "TEXT NOT NULL DEFAULT 'unknown'",
            "provenance": "TEXT",
        }.items():
            _add_column_if_missing(db, "scan_ingredient", name, ddl)
        for table in ("ingredient_info", "alternative_cache"):
            for name, ddl in {
                "expires_at": "TEXT",
                "prompt_version": "TEXT",
                "schema_version": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                _add_column_if_missing(db, table, name, ddl)

        now = _iso()
        for row in db.execute("SELECT id, created_at, status, public_id FROM scan").fetchall():
            updates: list[str] = []
            values: list[Any] = []
            if not row["public_id"]:
                updates.append("public_id=?")
                values.append(f"legacy-{row['id']}-{secrets.token_urlsafe(8)}")
            if not row["status"]:
                updates.append("status='completed'")
            if not db.execute("SELECT 1 FROM scan WHERE id=? AND updated_at IS NOT NULL", (row["id"],)).fetchone():
                updates.append("updated_at=?")
                values.append(row["created_at"] or now)
            if updates:
                values.append(row["id"])
                db.execute(f"UPDATE scan SET {', '.join(updates)} WHERE id=?", values)

        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scan_public_id ON scan(public_id) WHERE public_id IS NOT NULL"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scan_owner_idempotency "
            "ON scan(session_id, idempotency_key) "
            "WHERE session_id IS NOT NULL AND idempotency_key IS NOT NULL"
        )
        for statement in (
            "CREATE INDEX IF NOT EXISTS idx_scan_created ON scan(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_scan_status ON scan(status)",
            "CREATE INDEX IF NOT EXISTS idx_scan_session_created ON scan(session_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_scan_method_reason ON scan(scoring_method,fallback_reason)",
            "CREATE INDEX IF NOT EXISTS idx_scan_ing_scan ON scan_ingredient(scan_id)",
            "CREATE INDEX IF NOT EXISTS idx_scan_ing_ingredient ON scan_ingredient(ingredient_id)",
            "CREATE INDEX IF NOT EXISTS idx_scan_ing_flag ON scan_ingredient(flag)",
            "CREATE INDEX IF NOT EXISTS idx_provider_scan ON provider_attempt(scan_id, created_at)",
        ):
            db.execute(statement)
        db.execute(
            "INSERT OR IGNORE INTO schema_meta(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION, now),
        )
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def seed(kb: Any, path: Path | str = DB_PATH) -> None:
    initialize(path)
    with session(path) as db:
        for key, entry in kb.entries.items():
            db.execute(
                "INSERT OR IGNORE INTO ingredient(id,canonical,category,primary_flag,verified) VALUES(?,?,?,?,?)",
                (
                    key,
                    entry.get("canonical", key),
                    entry.get("category"),
                    entry.get("primary_flag"),
                    int(bool(entry.get("verified"))),
                ),
            )
            aliases = [(a, "name") for a in [entry.get("canonical", ""), *entry.get("aliases", [])] if a]
            aliases.extend((str(i), "ins") for i in entry.get("ins", []))
            for alias, kind in aliases:
                db.execute(
                    "INSERT OR IGNORE INTO ingredient_alias(ingredient_id,alias,kind) VALUES(?,?,?)",
                    (key, alias, kind),
                )
        for flag, row in kb.rules.get("flags", {}).items():
            db.execute(
                "INSERT OR REPLACE INTO flag_rule(flag,penalty,position_weighted,is_bonus) VALUES(?,?,?,0)",
                (flag, row.get("penalty", 0), int(bool(row.get("position_weighted")))),
            )
        for flag, penalty in kb.rules.get("bonus", {}).items():
            if flag != "cap":
                db.execute(
                    "INSERT OR REPLACE INTO flag_rule(flag,penalty,position_weighted,is_bonus) VALUES(?,?,0,1)",
                    (flag, penalty),
                )


def request_fingerprint(ingredients_text: str, profile: Any = None, force_mode: str = "auto") -> str:
    payload = json.dumps(
        {"ingredients_text": ingredients_text, "profile": profile, "force_mode": force_mode},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_public(row: sqlite3.Row) -> dict[str, Any]:
    created_at = row["created_at"]
    created_local = created_at
    if created_at:
        try:
            created_local = (datetime.fromisoformat(created_at) + timedelta(hours=5, minutes=30)).isoformat()
        except ValueError:
            created_local = created_at
    return {
        "public_id": row["public_id"],
        "id": row["public_id"],
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
        "created_at_local": created_local,
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "score": row["score"],
        "band": row["band"],
        "scoring_method": row["scoring_method"],
        "fallback_reason": row["fallback_reason"],
        "kb_coverage": row["kb_coverage"],
        "n_tokens": row["n_tokens"],
        "completeness": row["completeness"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
    }


def _get_scan_row(db: sqlite3.Connection, public_id: str | None = None, scan_id: int | None = None) -> sqlite3.Row | None:
    if public_id is not None:
        return db.execute("SELECT * FROM scan WHERE public_id=?", (public_id,)).fetchone()
    return db.execute("SELECT * FROM scan WHERE id=?", (scan_id,)).fetchone()


def create_scan(
    *,
    session_id: str | None,
    idempotency_key: str | None,
    request_id: str,
    request_fingerprint_value: str,
    source: str,
    n_tokens: int = 0,
    status: str = "received",
    path: Path | str = DB_PATH,
    parent_scan_id: int | None = None,
    kb_version: int = 0,
) -> dict[str, Any]:
    """Durably accept one logical request before expensive provider work."""
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(f"Unknown scan status: {status}")
    initialize(path)
    now = _iso()
    with session(path) as db:
        if session_id and idempotency_key:
            existing = db.execute(
                "SELECT * FROM scan WHERE session_id=? AND idempotency_key=?",
                (session_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["request_fingerprint"] != request_fingerprint_value:
                    raise IdempotencyConflict("This request key was already used for different input.")
                if existing["status"] not in _TERMINAL_STATUSES:
                    raise ScanInProgress("This scan is already being processed.", existing)
                return {**_row_public(existing), "_scan_id": existing["id"], "request_id": existing["request_id"], "reused": True}

        public_id = uuid4().hex
        cur = db.execute(
            "INSERT INTO scan(public_id,session_id,idempotency_key,request_id,request_fingerprint,status,created_at,updated_at,source,n_tokens,completeness,result_schema_version,scoring_version,kb_version,parent_scan_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,1,1,?,?)",
            (
                public_id,
                session_id,
                idempotency_key,
                request_id,
                request_fingerprint_value,
                status,
                now,
                now,
                source if source in {"camera", "upload", "paste"} else "paste",
                max(0, int(n_tokens)),
                "complete",
                kb_version,
                parent_scan_id,
            ),
        )
        row = _get_scan_row(db, scan_id=int(cur.lastrowid or 0))
        assert row is not None
        return {**_row_public(row), "_scan_id": row["id"], "request_id": request_id, "reused": False}


def get_scan(public_id: str, *, session_id: str | None, path: Path | str = DB_PATH) -> dict[str, Any] | None:
    initialize(path)
    with session(path) as db:
        row = db.execute(
            "SELECT * FROM scan WHERE public_id=? AND session_id=?",
            (public_id, session_id),
        ).fetchone()
        return _row_public(row) if row else None


def transition_scan(scan_id: int, new_status: str, *, path: Path | str = DB_PATH) -> None:
    if new_status not in LIFECYCLE_STATUSES:
        raise ValueError(f"Unknown scan status: {new_status}")
    with session(path) as db:
        row = _get_scan_row(db, scan_id=scan_id)
        if row is None:
            raise PersistenceError("Scan does not exist.")
        if new_status == row["status"]:
            return
        if new_status not in _LEGAL_TRANSITIONS.get(row["status"], set()):
            raise PersistenceError(f"Illegal scan lifecycle transition: {row['status']} -> {new_status}")
        now = _iso()
        db.execute(
            "UPDATE scan SET status=?,updated_at=?,completed_at=CASE WHEN ? IN ('completed','completed_limited','failed','cancelled','interrupted') THEN ? ELSE completed_at END WHERE id=?",
            (new_status, now, new_status, now if new_status in _TERMINAL_STATUSES else None, scan_id),
        )


def _assessment_state(ingredient: Any) -> str:
    if not getattr(ingredient, "matched", False):
        return "unknown"
    if getattr(ingredient, "flag", None):
        return "assessed"
    return "neutral"


def _sanitize_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"detected_text", "ingredients_text", "raw_prompt", "prompt", "provider_response"}:
                continue
            result[key] = _sanitize_snapshot(item)
        return result
    if isinstance(value, list):
        return [_sanitize_snapshot(item) for item in value]
    return value


def finalize_scan(
    scan_id: int,
    result: Any,
    tokens: list[Any],
    *,
    path: Path | str = DB_PATH,
    kb_version: int = 0,
    completeness: str = "complete",
) -> dict[str, Any]:
    """Atomically save the result snapshot and all ingredient children."""
    if completeness not in {"complete", "limited"}:
        raise ValueError("completeness must be complete or limited")
    with session(path) as db:
        row = _get_scan_row(db, scan_id=scan_id)
        if row is None:
            raise PersistenceError("Scan does not exist.")
        if row["status"] in {"completed", "completed_limited", "cancelled"}:
            if row["result_json"]:
                return _row_public(row)
            raise PersistenceError("Scan is already terminal.")
        if row["status"] != "analyzing":
            raise PersistenceError(f"Cannot finalize scan in {row['status']} state.")

        nova = getattr(result, "nova", None)
        snapshot = _sanitize_snapshot(result.model_dump(mode="json"))
        now = _iso()
        final_status = "completed" if getattr(result, "status", None) == "ok" and completeness == "complete" else "completed_limited"
        score = getattr(result, "score", None)
        db.execute(
            "UPDATE scan SET status=?,updated_at=?,completed_at=?,score=?,band=?,scoring_method=?,fallback_reason=?,nova_top=?,nova_confidence=?,rule_score=?,ml_score=?,kb_coverage=?,n_tokens=?,completeness=?,kb_version=?,result_json=? WHERE id=?",
            (
                final_status,
                now,
                now,
                score,
                getattr(result, "band", None),
                getattr(result, "scoring_method", None),
                getattr(result, "fallback_reason", None),
                getattr(nova, "top", None) if nova else None,
                getattr(nova, "confidence", None) if nova else None,
                getattr(result, "rule_score", None),
                getattr(result, "ml_score", None),
                getattr(result, "kb_coverage", None) or 0,
                len(tokens),
                completeness,
                kb_version,
                json.dumps(snapshot, ensure_ascii=False),
                scan_id,
            ),
        )
        db.execute("DELETE FROM scan_ingredient WHERE scan_id=?", (scan_id,))
        for ing in getattr(result, "ingredients", []) or []:
            ingredient_id = getattr(ing, "kb_id", None) if getattr(ing, "matched", False) else None
            if ingredient_id and db.execute("SELECT 1 FROM ingredient WHERE id=?", (ingredient_id,)).fetchone() is None:
                # A test/repair database may not have been seeded yet.  Keep
                # the parsed child and its assessment, but do not violate the
                # normalized FK or lose the whole scan snapshot.
                ingredient_id = None
            db.execute(
                "INSERT INTO scan_ingredient(scan_id,position,raw_name,normalized_name,ingredient_id,flag,points,assessment_state,provenance) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    scan_id,
                    int(getattr(ing, "position", 0)),
                    str(getattr(ing, "raw", getattr(ing, "name", ""))),
                    str(getattr(ing, "name", "")),
                    ingredient_id,
                    getattr(ing, "flag", None),
                    float(getattr(ing, "points", 0)),
                    _assessment_state(ing),
                    "knowledge_base" if getattr(ing, "matched", False) else "unknown",
                ),
            )
        saved = _get_scan_row(db, scan_id=scan_id)
        assert saved is not None
        return _row_public(saved)


def fail_scan(scan_id: int, *, reason: str = "persistence_failed", path: Path | str = DB_PATH) -> None:
    """Record a safe terminal failure without storing provider/error payloads."""
    with session(path) as db:
        row = _get_scan_row(db, scan_id=scan_id)
        if row is None or row["status"] in {"completed", "completed_limited", "cancelled"}:
            return
        now = _iso()
        db.execute(
            "UPDATE scan SET status='failed',updated_at=?,completed_at=?,fallback_reason=?,completeness='limited' WHERE id=?",
            (now, now, reason[:80], scan_id),
        )


def record_scan(result: Any, tokens: list[Any], path: Path | str = DB_PATH, *, source: str = "paste") -> dict[str, Any]:
    """Compatibility helper for local scripts/tests; failures are no longer swallowed."""
    accepted = create_scan(
        session_id=None,
        idempotency_key=None,
        request_id=uuid4().hex,
        request_fingerprint_value=uuid4().hex,
        source=source,
        n_tokens=len(tokens),
        path=path,
    )
    transition_scan(accepted["_scan_id"], "analyzing", path=path)
    return finalize_scan(accepted["_scan_id"], result, tokens, path=path)


def history(
    limit: int = 50,
    path: Path | str = DB_PATH,
    *,
    session_id: str | None = None,
    offset: int = 0,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return history; callers with a session get only their own rows."""
    initialize(path)
    with session(path) as db:
        where = []
        args: list[Any] = []
        if session_id is not None:
            where.append("session_id=?")
            args.append(session_id)
        if search:
            term = f"%{search.strip()}%"
            where.append("(band LIKE ? OR scoring_method LIKE ? OR fallback_reason LIKE ? OR source LIKE ? OR result_json LIKE ?)")
            args.extend([term] * 5)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = db.execute(
            f"SELECT * FROM scan {clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*args, max(1, min(int(limit), 100)), max(0, int(offset))),
        ).fetchall()
        return [_row_public(row) for row in rows]


def delete_scan(public_id: str, *, session_id: str, path: Path | str = DB_PATH) -> bool:
    initialize(path)
    with session(path) as db:
        cur = db.execute("DELETE FROM scan WHERE public_id=? AND session_id=?", (public_id, session_id))
        return cur.rowcount > 0


def clear_history(*, session_id: str, path: Path | str = DB_PATH) -> int:
    initialize(path)
    with session(path) as db:
        cur = db.execute("DELETE FROM scan WHERE session_id=?", (session_id,))
        return cur.rowcount


def stats(path: Path | str = DB_PATH) -> dict[str, Any]:
    """Local-only diagnostic helper; not exposed as a customer endpoint."""
    initialize(path)
    with session(path) as db:
        return {
            "scans": db.execute("SELECT count(*) FROM scan").fetchone()[0],
            "ingredients": db.execute("SELECT count(*) FROM ingredient").fetchone()[0],
            "aliases": db.execute("SELECT count(*) FROM ingredient_alias").fetchone()[0],
            "flag_rules": db.execute("SELECT count(*) FROM flag_rule").fetchone()[0],
            "ingredient_info_cache": db.execute("SELECT count(*) FROM ingredient_info").fetchone()[0],
            "alternative_cache": db.execute("SELECT count(*) FROM alternative_cache").fetchone()[0],
        }


def demo_queries(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    sql_path = Path(__file__).parents[2] / ".." / "docs" / "QUERIES.sql"
    content = sql_path.resolve().read_text(encoding="utf-8")
    initialize(path)
    with session(path) as db:
        output = []
        for chunk in content.split("-- QUERY:")[1:]:
            title, sql = chunk.split("\n", 1)
            output.append({"title": title.strip(), "rows": [dict(row) for row in db.execute(sql.strip())]})
        return output


def explain_indexed_recent_query(path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with session(path) as db:
        return [
            dict(row)
            for row in db.execute(
                "EXPLAIN QUERY PLAN SELECT id,score,band FROM scan ORDER BY created_at DESC LIMIT 10"
            )
        ]


def normalize_cache_name(name: str) -> str:
    return " ".join(name.casefold().split())


def _cache_valid(row: sqlite3.Row, *, now: datetime | None = None) -> bool:
    expires_at = row["expires_at"] if "expires_at" in row.keys() else None
    if expires_at:
        try:
            return datetime.fromisoformat(expires_at) > (now or utc_now())
        except ValueError:
            return False
    return True


def cached_ingredient_info(
    names: list[str],
    path: Path | str = DB_PATH,
    *,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    keys = sorted({normalize_cache_name(n) for n in names if n and n.strip()})
    if not keys:
        return {}
    initialize(path)
    with session(path) as db:
        placeholders = ",".join("?" for _ in keys)
        rows = db.execute(f"SELECT * FROM ingredient_info WHERE name_norm IN ({placeholders})", keys).fetchall()
        output: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not _cache_valid(row):
                continue
            if model and row["model"] and row["model"] != model:
                continue
            if prompt_version and row["prompt_version"] and row["prompt_version"] != prompt_version:
                continue
            db.execute("UPDATE ingredient_info SET hit_count=hit_count+1 WHERE name_norm=?", (row["name_norm"],))
            output[row["name_norm"]] = dict(row)
        return output


def save_ingredient_info(
    rows: list[dict[str, Any]],
    model: str,
    path: Path | str = DB_PATH,
    *,
    prompt_version: str = "full-analysis-v2",
    ttl_seconds: int = 30 * 24 * 60 * 60,
) -> None:
    initialize(path)
    now = utc_now()
    expires = now + timedelta(seconds=max(0, int(ttl_seconds)))
    with session(path) as db:
        for row in rows:
            name = row.get("name")
            if not name or not row.get("what_it_is") or not row.get("health_note"):
                continue
            db.execute(
                "INSERT INTO ingredient_info(name_norm,what_it_is,health_note,concern_level,source,model,generated_at,expires_at,prompt_version,schema_version,verified) "
                "VALUES(?,?,?,?, 'gemini',?,?,?,?,?,0) "
                "ON CONFLICT(name_norm) DO UPDATE SET what_it_is=excluded.what_it_is,health_note=excluded.health_note,concern_level=excluded.concern_level,source='gemini',model=excluded.model,generated_at=excluded.generated_at,expires_at=excluded.expires_at,prompt_version=excluded.prompt_version,schema_version=excluded.schema_version,verified=0",
                (
                    normalize_cache_name(str(name)),
                    str(row["what_it_is"]),
                    str(row["health_note"]),
                    row.get("concern_level", row.get("risk_level", "none")),
                    model,
                    _iso(now),
                    _iso(expires),
                    prompt_version,
                    CACHE_SCHEMA_VERSION,
                ),
            )


def cached_alternatives(
    cache_key: str,
    path: Path | str = DB_PATH,
    *,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any] | None:
    initialize(path)
    with session(path) as db:
        row = db.execute("SELECT * FROM alternative_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None or not _cache_valid(row):
            return None
        if model and row["model"] and row["model"] != model:
            return None
        if prompt_version and row["prompt_version"] and row["prompt_version"] != prompt_version:
            return None
        db.execute("UPDATE alternative_cache SET hit_count=hit_count+1 WHERE cache_key=?", (cache_key,))
        return dict(row)


def save_alternatives(
    cache_key: str,
    alternatives: list[dict[str, Any]],
    model: str,
    path: Path | str = DB_PATH,
    *,
    prompt_version: str = "full-analysis-v2",
    ttl_seconds: int = 30 * 24 * 60 * 60,
) -> None:
    initialize(path)
    now = utc_now()
    expires = now + timedelta(seconds=max(0, int(ttl_seconds)))
    with session(path) as db:
        db.execute(
            "INSERT INTO alternative_cache(cache_key,content_json,source,model,generated_at,expires_at,prompt_version,schema_version,verified) "
            "VALUES(?,?, 'gemini',?,?,?,?,?,0) "
            "ON CONFLICT(cache_key) DO UPDATE SET content_json=excluded.content_json,source='gemini',model=excluded.model,generated_at=excluded.generated_at,expires_at=excluded.expires_at,prompt_version=excluded.prompt_version,schema_version=excluded.schema_version,verified=0",
            (
                cache_key,
                json.dumps(alternatives, ensure_ascii=False),
                model,
                _iso(now),
                _iso(expires),
                prompt_version,
                CACHE_SCHEMA_VERSION,
            ),
        )


def record_provider_attempt(
    scan_id: int,
    *,
    operation: str,
    attempt_number: int,
    outcome: str,
    model: str | None = None,
    attempted: bool = True,
    status_code: int | None = None,
    duration_ms: int | None = None,
    fallback_category: str | None = None,
    usage: dict[str, Any] | None = None,
    path: Path | str = DB_PATH,
) -> None:
    initialize(path)
    with session(path) as db:
        db.execute(
            "INSERT INTO provider_attempt(scan_id,operation,attempted,attempt_number,model,outcome,status_code,duration_ms,fallback_category,usage_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                scan_id,
                operation[:80],
                int(bool(attempted)),
                int(attempt_number),
                model,
                outcome[:80],
                status_code,
                duration_ms,
                fallback_category[:80] if fallback_category else None,
                json.dumps(usage, ensure_ascii=False) if usage else None,
                _iso(),
            ),
        )


def reconcile_interrupted(path: Path | str = DB_PATH, *, older_than_seconds: int = 120) -> int:
    """Mark abandoned in-flight work after a process restart."""
    initialize(path)
    cutoff = utc_now() - timedelta(seconds=max(1, older_than_seconds))
    with session(path) as db:
        rows = db.execute(
            "SELECT id FROM scan WHERE status IN ('received','extracting','analyzing') AND updated_at < ?",
            (_iso(cutoff),),
        ).fetchall()
        now = _iso()
        for row in rows:
            db.execute(
                "UPDATE scan SET status='interrupted',updated_at=?,completed_at=?,fallback_reason='interrupted' WHERE id=?",
                (now, now, row["id"]),
            )
        return len(rows)
