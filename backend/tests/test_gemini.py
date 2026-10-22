from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.core import gemini
from app.core.database import connect, initialize, save_alternatives, save_ingredient_info
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


def test_complete_list_is_sent_to_gemini_even_when_database_has_notes(monkeypatch):
    path = temp_db()
    names = ["raw sugar", "salt"]
    save_ingredient_info([{"name":"raw sugar","what_it_is":"cached note","health_note":"cached note","concern_level":"low"}], "old-model", path)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    captured = []
    response = {"items":[
        {"name":"raw sugar","what_it_is":"A sweetener.","health_note":"Frequent high intake may affect dietary balance.","risk_level":"medium"},
        {"name":"salt","what_it_is":"A mineral seasoning.","health_note":"High intake may contribute to excess sodium.","risk_level":"high"}],
        "alternatives":[{"type":"Unsweetened oats","reason":"Less added sugar."},{"type":"Fresh fruit","reason":"A naturally sweet option."},{"type":"Unsalted nuts","reason":"A lower-sodium snack."}]}
    monkeypatch.setattr(gemini, "_request_json", lambda prompt, schema: captured.append((prompt,schema)) or response)
    result = gemini.analyze_ingredient_list("raw sugar, salt", names, path=path)
    assert result["source"] == "gemini"
    assert [item["risk_level"] for item in result["ingredient_info"]] == ["medium", "high"]
    assert len(result["alternatives"]) == 3
    assert '"ingredients_text": "raw sugar, salt"' in captured[0][0]
    assert captured[0][1] is gemini._FULL_ANALYSIS_SCHEMA
    path.unlink(missing_ok=True)


def test_failed_full_list_analysis_uses_database_fallback_only(monkeypatch):
    path = temp_db()
    names = ["sugar", "salt"]
    save_ingredient_info([{"name":"Sugar","what_it_is":"A sweetener.","health_note":"Cached general note.","concern_level":"medium"}], "old-model", path)
    cache_key = gemini._list_cache_key(names)
    save_alternatives(cache_key, [{"type":"Unsweetened cereal","reason":"Avoids added sugar."}], "old-model", path)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini, "_request_json", lambda *a, **k: None)
    result = gemini.analyze_ingredient_list("sugar, salt", names, path=path)
    assert result["source"] == "database_fallback"
    assert result["ingredient_info"][0]["name"] == "sugar"
    assert result["ingredient_info"][0]["source"] == "database_fallback"
    assert result["alternatives"][0]["source"] == "database_fallback"
    path.unlink(missing_ok=True)


def test_gemini_key_is_sent_in_header_not_logged_url(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    captured = {}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"candidates":[{"content":{"parts":[{"text":"{\"ok\":true}"}]}}]}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr(gemini.httpx, "post", fake_post)
    assert gemini._request_json("safe prompt", {"type":"OBJECT"}) == {"ok":True}
    assert "test-key" not in captured["url"]
    assert "params" not in captured
    assert captured["headers"]["x-goog-api-key"] == "test-key"


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
    monkeypatch.setattr(gemini, "analyze_ingredient_list", lambda text, names, **kwargs: {"ingredient_info":[],"alternatives":[],"source":"gemini"})
    monkeypatch.setattr("app.api.routes.record_scan", lambda *a, **k: None)
    client = TestClient(app)
    response = client.post("/api/scan-image", files={"file":("label.jpg", b"jpeg-data", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["source"] == "camera"
    assert response.json()["detected_text"] == "oats, salt"
    too_large = client.post("/api/scan-image", files={"file":("large.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")})
    assert too_large.status_code == 413


def test_text_analyze_sends_the_full_submitted_list_to_enrichment(monkeypatch):
    captured = {}
    def mock_analysis(text, names, **kwargs):
        captured.update(text=text, names=names)
        return {"ingredient_info":[],"alternatives":[],"source":"gemini"}
    monkeypatch.setattr(gemini, "analyze_ingredient_list", mock_analysis)
    monkeypatch.setattr("app.api.routes.record_scan", lambda *a, **k: None)
    response = TestClient(app).post("/api/analyze", json={"ingredients_text":"Oats, palm oil, salt"})
    assert response.status_code == 200
    assert captured["text"] == "Oats, palm oil, salt"
    assert captured["names"] == ["Oats", "palm oil", "salt"]
    assert response.json()["ingredient_analysis_source"] == "gemini"
