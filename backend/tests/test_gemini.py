from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.core import gemini
from app.core.database import connect, initialize
from fastapi.testclient import TestClient
from app.main import app


def temp_db():
    path = Path(__file__).parents[1] / "data" / f"gemini-test-{uuid4().hex}.db"
    initialize(path)
    return path


def test_ingredient_info_uses_cache_and_marks_generated(monkeypatch):
    path = temp_db()
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: {"items":[{"name":"Sugar","what_it_is":"A sweetener", "health_note":"Frequent high intake may affect overall diet quality.", "concern_level":"medium"}]})
    result = gemini.ingredient_info(["Sugar"], path=path)
    assert result[0]["ai_generated"] is True
    assert result[0]["source"] == "gemini"
    assert result[0]["concern_level"] == "medium"
    # The second call is served from SQLite without another generation request.
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")))
    assert gemini.ingredient_info([" sugar "], path=path)[0]["health_note"] == result[0]["health_note"]
    path.unlink(missing_ok=True)


def test_owner_kb_text_overrides_gemini(monkeypatch):
    path = temp_db()
    class KB:
        entries = {"salt":{"canonical":"Salt","aliases":["salt"],"explanation":"Owner-authored note.","verified":True}}
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call Gemini")))
    item = gemini.ingredient_info(["Salt"], kb=KB(), path=path)[0]
    assert item["health_note"] == "Owner-authored note."
    assert item["ai_generated"] is False
    assert item["verified"] is True
    path.unlink(missing_ok=True)


def test_gemini_failure_degrades_and_image_extraction_is_bounded(monkeypatch):
    path = temp_db()
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: None)
    assert gemini.ingredient_info(["unknown ingredient"], path=path) == []
    assert gemini.alternatives(["added_sugar"], 30, path=path) == []
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: {"found":True,"ingredients_text":"x"*4001,"language":"en","confidence":0.8})
    assert gemini.extract_ingredients(b"image", "image/jpeg") is None
    path.unlink(missing_ok=True)


def test_scan_image_uses_mocked_ocr_and_rejects_over_limit(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini, "extract_ingredients", lambda image, mime: {"found":True,"ingredients_text":"oats, salt","language":"en","confidence":0.9,"ai_generated":True})
    monkeypatch.setattr("app.api.routes.record_scan", lambda *a, **k: None)
    client = TestClient(app)
    response = client.post("/api/scan-image", files={"file":("label.jpg", b"jpeg-data", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["source"] == "camera"
    assert response.json()["detected_text"] == "oats, salt"
    too_large = client.post("/api/scan-image", files={"file":("large.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")})
    assert too_large.status_code == 413
