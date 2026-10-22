"""
test_gate_orchestrator.py - Unit and API tests for Fallback Gate, Orchestrator, and /api/analyze (M3a).

Covers all 18 test cases specified in Milestone M3a:
  1. ML accepted
  2. not ready (model_loading)
  3. load error (model_error)
  4. predict raises (model_error; never 500)
  5. timeout (model_timeout)
  6. low confidence (< 0.60)
  7. NOVA 2 below 0.80 (weak_class_uncertain)
  8. small margin (< 0.15, ambiguous_prediction)
  9. optimistic gap (> 25 pts, ml_rule_disagreement)
 10. pessimistic gap (> 45 pts, ml_rule_disagreement)
 11. both gap checks skipped at low coverage (< 0.60)
 12. unsupported_language (< 2 Latin tokens when ML_HINDI_SUPPORTED=false)
 13. forced_rules (force_mode='rules')
 14. NaN probabilities (model_error)
 15. probabilities not summing to about 1 (model_error)
 16. insufficient_input (tokens < 2 or chars < 15)
 17. not_food_text (coverage < 0.30 and not looks_like_food)
 18. API schema test via TestClient (/api/analyze and /api/health)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import set_knowledge_base
from app.config import settings
from app.core.gate import check_gate
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.base import ModelError, ModelNotReady, NovaPrediction
from app.core.ml.manager import get_model, init_background_model_loader, set_model
from app.core.scoring import analyze
from app.main import app
from app.schemas import AnalyzeResponse
from tests.mocks import MockNovaModel


@pytest.fixture(scope="module")
def kb():
    k = KnowledgeBase()
    k.load()
    set_knowledge_base(k)
    return k


@pytest.fixture(autouse=True)
def reset_model(monkeypatch):
    """Reset the model to a fresh MockNovaModel before each test."""
    monkeypatch.setattr(settings, "ml_enabled", True)
    mock = MockNovaModel(status="ready")
    set_model(mock)
    yield mock
    set_model(None)


# ── 1. ML accepted ─────────────────────────────────────────────────────────────

def test_ml_accepted(kb, reset_model):
    """Clean high-confidence prediction accepted by gate; score is ml_score."""
    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    mock = reset_model
    mock.set_prediction(top=4, confidence=0.92, margin=0.85)

    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "ml_assisted"
    assert res.fallback_reason is None
    assert res.nova is not None
    assert res.nova.top == 4
    assert res.nova.confidence == 0.92
    assert res.score == res.ml_score
    assert res.rule_score is not None


# ── 2. Not ready (model_loading) ───────────────────────────────────────────────

def test_model_not_ready(kb, reset_model):
    """Model still loading returns rule result with reason model_loading."""
    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    mock = reset_model
    mock.status = "loading"

    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_loading"
    assert res.score == res.rule_score
    assert res.nova is None


# ── 3. Load error (model_error) ────────────────────────────────────────────────

def test_model_load_error(kb):
    """Model load failure sets status=error and analyze falls back to model_error."""
    mock = MockNovaModel()
    mock.load_exception = RuntimeError("Failed to load safetensors")
    try:
        mock.load()
    except RuntimeError:
        pass
    assert mock.status == "error"

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_error"
    assert res.score == res.rule_score


# ── 4. Predict raises (model_error; never 500) ──────────────────────────────────

def test_model_predict_raises(kb, reset_model):
    """Exception inside model.predict must not crash the app, but fallback to model_error."""
    mock = reset_model
    mock.predict_exception = RuntimeError("Unexpected runtime exception in inference")

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_error"
    assert res.score == res.rule_score


# ── 5. Timeout (model_timeout) ─────────────────────────────────────────────────

def test_model_timeout(kb, reset_model, monkeypatch):
    """Inference exceeding timeout falls back to model_timeout."""
    mock = reset_model
    mock.delay_s = 0.2
    monkeypatch.setattr(settings, "ml_timeout_s", 0.05)

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_timeout"
    assert res.score == res.rule_score


# ── 6. Low confidence (< 0.60) ─────────────────────────────────────────────────

def test_low_confidence(kb, reset_model):
    """Confidence below 0.60 falls back with low_confidence."""
    mock = reset_model
    mock.set_prediction(
        top=4,
        confidence=0.52,
        margin=0.20,
        probs={1: 0.10, 2: 0.10, 3: 0.28, 4: 0.52},
    )

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "low_confidence"
    # When prediction exists, nova and ml_score are retained for UI transparency (§9.2)
    assert res.nova is not None
    assert res.nova.confidence == 0.52
    assert res.ml_score is not None
    assert res.score == res.rule_score


# ── 7. NOVA 2 below 0.80 (weak_class_uncertain) ────────────────────────────────

def test_nova2_below_080(kb, reset_model):
    """Top class NOVA 2 requires confidence >= 0.80; 0.72 triggers weak_class_uncertain."""
    mock = reset_model
    mock.set_prediction(
        top=2,
        confidence=0.72,
        margin=0.45,
        probs={1: 0.10, 2: 0.72, 3: 0.10, 4: 0.08},
    )

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "weak_class_uncertain"


# ── 8. Small margin (< 0.15) ───────────────────────────────────────────────────

def test_small_margin(kb, reset_model):
    """Top-1 minus top-2 margin < 0.15 triggers ambiguous_prediction."""
    mock = reset_model
    mock.set_prediction(
        top=4,
        confidence=0.62,
        margin=0.08,  # top1 (0.62) - top2 (0.54) would be < 0.15
        probs={1: 0.05, 2: 0.05, 3: 0.28, 4: 0.62},
    )

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "ambiguous_prediction"


# ── 9. Optimistic gap (> 25 pts) ───────────────────────────────────────────────

def test_optimistic_gap(kb, reset_model):
    """
    ML score far more reassuring than rule score (> 25 pts) at kb_coverage >= 0.60
    triggers ml_rule_disagreement.
    """
    text = "Refined wheat flour, Palm oil, Salt, Flavour enhancer (INS 621), Flavour enhancer (INS 627), Sugar"
    mock = reset_model
    mock.set_prediction(top=1, confidence=0.90, margin=0.80)

    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "ml_rule_disagreement"
    assert res.ml_score - res.rule_score > 25


# ── 10. Pessimistic gap (> 45 pts) ─────────────────────────────────────────────

def test_pessimistic_gap(kb, reset_model):
    """
    Rule score far more reassuring than ML score (> 45 pts) at kb_coverage >= 0.60
    triggers ml_rule_disagreement.
    """
    mock = reset_model
    mock.set_prediction(top=4, confidence=0.90, margin=0.80)

    reason = check_gate(
        pred=mock._prediction,
        rule_score=90,
        ml_score=40,
        kb_coverage=0.80,
        tokens=["token1", "token2"],
    )
    assert reason == "ml_rule_disagreement"


# ── 11. Both gap checks skipped at low coverage ────────────────────────────────

def test_gap_checks_skipped_at_low_coverage(kb, reset_model):
    """
    When kb_coverage < 0.60, the rule score is considered unreliable,
    so optimistic and pessimistic gap checks are skipped.
    """
    mock = reset_model
    reason = check_gate(
        pred=mock._prediction,
        rule_score=30,
        ml_score=85,
        kb_coverage=0.40,  # low coverage!
        tokens=["Salt", "Potato", "Black pepper"],
    )
    assert reason is None  # Skipped!


# ── 12. Unsupported language (< 2 Latin tokens) ────────────────────────────────

def test_unsupported_language(kb, reset_model):
    """Fewer than 2 Latin tokens when ML_HINDI_SUPPORTED=false triggers unsupported_language."""
    # 1 Latin token ("Sugar") + 2 Hindi tokens -> Latin count is 1 (< 2)
    text = "Sugar, चीनी, पाम तेल"
    mock = reset_model

    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "unsupported_language"

    # Also verify direct gate check on pure Devanagari tokens
    gate_reason = check_gate(
        pred=mock._prediction,
        tokens=["गेहूं का आटा", "चीनी", "पाम तेल"],
        kb_coverage=0.8,
    )
    assert gate_reason == "unsupported_language"


# ── 13. Forced rules (force_mode='rules') ──────────────────────────────────────

def test_forced_rules(kb, reset_model):
    """force_mode='rules' immediately bypasses ML with fallback_reason forced_rules."""
    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    mock = reset_model

    res = analyze(text=text, force_mode="rules", kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "forced_rules"
    assert res.nova is None
    assert res.ml_score is None


# ── 14. NaN probabilities (model_error) ────────────────────────────────────────

def test_nan_probabilities(kb, reset_model):
    """Model returning NaN in probabilities must fail gracefully with model_error."""
    mock = reset_model
    mock._prediction = NovaPrediction(
        probs={1: float("nan"), 2: 0.1, 3: 0.1, 4: 0.8},
        top=4,
        confidence=0.8,
        margin=0.7,
        latency_ms=10,
        model_id="mock",
    )

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_error"


# ── 15. Probabilities not summing to about 1 (model_error) ─────────────────────

def test_probs_not_summing_to_one(kb, reset_model):
    """Model returning probabilities that do not sum to ~1.0 triggers model_error."""
    mock = reset_model
    mock._prediction = NovaPrediction(
        probs={1: 0.2, 2: 0.2, 3: 0.2, 4: 0.1},  # Sum = 0.70
        top=1,
        confidence=0.2,
        margin=0.0,
        latency_ms=10,
        model_id="mock",
    )

    text = "Refined wheat flour, Sugar, Palm oil, Salt"
    res = analyze(text=text, kb=kb, model=mock)
    assert res.status == "ok"
    assert res.scoring_method == "rule_based"
    assert res.fallback_reason == "model_error"


# ── 16. Insufficient input ─────────────────────────────────────────────────────

def test_insufficient_input(kb, reset_model):
    """Input with 1 token or < 15 characters returns status insufficient_input."""
    res_short = analyze(text="Sugar", kb=kb, model=reset_model)
    assert res_short.status == "insufficient_input"
    assert res_short.scoring_method is None
    assert "Please paste at least two ingredients" in (res_short.message or "")


# ── 17. Not food text ──────────────────────────────────────────────────────────

def test_not_food_text(kb, reset_model):
    """Non-food input returns status not_food_text."""
    text = "Plastic casing, copper wiring, lithium battery"
    res = analyze(text=text, kb=kb, model=reset_model)
    assert res.status == "not_food_text"
    assert res.scoring_method is None
    assert "not look like an ingredient list" in (res.message or "")


# ── 18. API schema test via TestClient ─────────────────────────────────────────

def test_api_schema_and_health_via_testclient(kb, reset_model):
    """Test full API contract of POST /api/analyze and GET /api/health with TestClient."""
    client = TestClient(app)

    # 1. Health check
    h_resp = client.get("/api/health")
    assert h_resp.status_code == 200
    h_data = h_resp.json()
    assert h_data["status"] == "ok"
    assert h_data["ml_status"] == "ready"
    assert h_data["backend"] == "minilm_head"
    assert h_data["gemini_status"] in ["configured", "missing_key"]
    assert "features" in h_data

    # 2. Analyze check
    payload = {
        "ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt",
        "profile": {"conditions": ["diabetes"]},
        "force_mode": "auto",
    }
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # Exact schema verification against ARCHITECTURE §9.2
    assert data["status"] == "ok"
    assert isinstance(data["score"], int)
    assert data["band"] in ["Low Risk", "Moderate Risk", "High Risk"]
    assert data["scoring_method"] == "ml_assisted"
    assert data["fallback_reason"] is None
    assert isinstance(data["rule_score"], int)
    assert isinstance(data["ml_score"], int)
    assert data["nova"]["top"] == 4
    assert isinstance(data["nova"]["probs"], dict)
    assert "4" in data["nova"]["probs"]
    assert data["nova_badge"]["source"] == "unavailable"
    assert data["nutriscore"]["status"] == "not_provided"
    assert data["language"]["detected"] == "latin"
    assert len(data["ingredients"]) >= 4
    assert data["disclaimer"] is not None
    assert data["attribution"] is not None
    assert data["low_coverage_warning"] is False
    assert len(data["profile_effects"]) >= 1
