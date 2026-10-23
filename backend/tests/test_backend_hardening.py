from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import set_knowledge_base
from app.config import settings
from app.core import gemini
from app.core.database import (
    IdempotencyConflict,
    create_scan,
    finalize_scan,
    get_scan,
    history,
    initialize,
    transition_scan,
)
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import set_model
from app.core.parser import parse
from app.core.scoring import analyze
from app.main import app
from tests.mocks import MockNovaModel


def temp_db(tmp_path: Path) -> Path:
    return tmp_path / f"nutrisnap-{uuid4().hex}.db"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, *, retry_after: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {"retry-after": retry_after} if retry_after else {}

    def json(self):
        return self._payload


def provider_payload() -> dict:
    return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}


def test_gemini_retries_only_bounded_transient_failures(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_max_attempts", 3)
    monkeypatch.setattr(settings, "gemini_backoff_s", 0.0)
    monkeypatch.setattr(gemini.time, "sleep", lambda _: None)
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(503, {"error": "temporary"})

    monkeypatch.setattr(gemini.httpx, "post", fake_post)
    outcome = gemini._request_json_detailed("safe prompt", {"type": "OBJECT"})
    assert outcome.data is None
    assert outcome.category == "transient_server_failure"
    assert outcome.attempts == 3
    assert len(calls) == 3


def test_gemini_honours_retry_after_then_accepts_response(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_max_attempts", 3)
    monkeypatch.setattr(settings, "gemini_backoff_s", 0.0)
    sleeps = []
    monkeypatch.setattr(gemini.time, "sleep", lambda value: sleeps.append(value))
    responses = [FakeResponse(429, {"error": "rate limited"}, retry_after="0"), FakeResponse(200, provider_payload())]
    monkeypatch.setattr(gemini.httpx, "post", lambda *args, **kwargs: responses.pop(0))
    outcome = gemini._request_json_detailed("safe prompt", {"type": "OBJECT"})
    assert outcome.ok
    assert outcome.attempts == 2
    assert sleeps == []


def test_partial_gemini_result_is_preserved_and_unknown_stays_unknown(monkeypatch, tmp_path):
    path = temp_db(tmp_path)
    initialize(path)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    response = {
        "items": [
            {"name": "Sugar", "what_it_is": "A sweetener", "health_note": "Keep intake moderate.", "risk_level": "medium"},
            {"name": "not-on-label", "what_it_is": "Invented", "health_note": "Invented", "risk_level": "low"},
        ],
        "alternatives": [{"type": "Unsweetened oats", "reason": "A generic lower-sugar option."}],
    }
    monkeypatch.setattr(gemini, "_request_json", lambda *args, **kwargs: response)
    result = gemini.analyze_ingredient_list("Sugar, Mystery powder", ["Sugar", "Mystery powder"], path=path)
    assert result["source"] == "mixed"
    assert [item["name"] for item in result["ingredient_info"]] == ["Sugar", "Mystery powder"]
    assert result["ingredient_info"][0]["source"] == "gemini"
    assert result["ingredient_info"][1]["risk_level"] == "unknown"
    assert len(result["alternatives"]) == 1


def test_scan_lifecycle_idempotency_and_session_scope(tmp_path):
    path = temp_db(tmp_path)
    initialize(path)
    kb = KnowledgeBase()
    kb.load()
    result = analyze("Oats, salt, water", kb=kb)
    accepted = create_scan(
        session_id="session-a",
        idempotency_key="key-a",
        request_id="request-a",
        request_fingerprint_value="fingerprint-a",
        source="paste",
        path=path,
    )
    assert accepted["status"] == "received"
    transition_scan(accepted["_scan_id"], "analyzing", path=path)
    saved = finalize_scan(accepted["_scan_id"], result, parse("Oats, salt, water"), path=path)
    assert saved["status"] == "completed"
    assert saved["public_id"]

    reused = create_scan(
        session_id="session-a",
        idempotency_key="key-a",
        request_id="request-b",
        request_fingerprint_value="fingerprint-a",
        source="paste",
        path=path,
    )
    assert reused["reused"] is True
    assert reused["public_id"] == saved["public_id"]
    assert len(history(path=path, session_id="session-a")) == 1
    assert history(path=path, session_id="session-b") == []
    assert get_scan(saved["public_id"], session_id="session-b", path=path) is None
    with pytest.raises(IdempotencyConflict):
        create_scan(
            session_id="session-a",
            idempotency_key="key-a",
            request_id="request-c",
            request_fingerprint_value="different-fingerprint",
            source="paste",
            path=path,
        )


def test_initialize_repairs_legacy_provider_attempt_foreign_key(tmp_path):
    path = temp_db(tmp_path)
    initialize(path)
    import sqlite3

    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE provider_attempt RENAME TO provider_attempt_legacy_fk")
        db.execute(
            "CREATE TABLE provider_attempt (id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scan_legacy(id) ON DELETE CASCADE, operation TEXT NOT NULL, attempted INTEGER NOT NULL DEFAULT 1, attempt_number INTEGER NOT NULL, model TEXT, outcome TEXT NOT NULL, status_code INTEGER, duration_ms INTEGER, fallback_category TEXT, usage_json TEXT, created_at TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO provider_attempt SELECT * FROM provider_attempt_legacy_fk"
        )
        db.execute("DROP TABLE provider_attempt_legacy_fk")

    initialize(path)
    with sqlite3.connect(path) as db:
        foreign_key = db.execute("PRAGMA foreign_key_list(provider_attempt)").fetchone()
        assert foreign_key[2] == "scan"


def test_public_routes_are_scoped_and_internal_routes_are_removed(monkeypatch, tmp_path):
    path = temp_db(tmp_path)
    monkeypatch.setattr(settings, "database_path", str(path))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    kb = KnowledgeBase()
    kb.load()
    set_knowledge_base(kb)
    set_model(MockNovaModel(status="ready"))

    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        json={"ingredients_text": "Oats, salt, water"},
        headers={"Idempotency-Key": "route-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["persisted"] is True
    assert data["scan_id"]
    assert data["save_status"] == "saved"
    assert "model_id" not in (data.get("nova") or {})
    assert "latency_ms" not in (data.get("nova") or {})
    assert all("model" not in item for item in data.get("ingredient_info", []))
    assert all("original_source" not in item for item in data.get("ingredient_info", []))
    assert any("HttpOnly" in value for value in response.headers.get_list("set-cookie"))

    reused = client.post(
        "/api/analyze",
        json={"ingredients_text": "Oats, salt, water"},
        headers={"Idempotency-Key": "route-key"},
    )
    assert reused.status_code == 200
    assert reused.json()["save_status"] == "reused"
    assert len(client.get("/api/history").json()["items"]) == 1
    assert client.get("/api/stats").status_code == 404
    assert client.get("/api/queries").status_code == 404
    assert client.get("/docs").status_code == 404

    other = TestClient(app)
    assert other.get("/api/history").json()["items"] == []
