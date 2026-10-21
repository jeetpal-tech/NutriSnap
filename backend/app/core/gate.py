"""
gate.py - Fallback gate for ML-assisted scoring (ARCHITECTURE §7.3).

Inputs:
  - pred: NovaPrediction | None
  - rule_score: int
  - ml_score: int | None
  - kb_coverage: float
  - tokens: list[IngredientToken] | list[str] | None
  - model_status: Literal["loading", "ready", "error", "disabled"]
  - error: Exception | str | None
  - force_mode: Literal["auto", "rules"]
  - settings_obj: Settings (default app.config.settings)

Output:
  None (use ML) or fallback reason code (str)
"""
from __future__ import annotations

import concurrent.futures
import math
import re
from typing import Any

from app.config import Settings, settings as default_settings
from app.core.ml.base import ModelError, ModelNotReady, NovaPrediction


def count_latin_tokens(tokens: list[Any]) -> int:
    """
    Count tokens that contain at least one Latin-script character [a-zA-Z].
    Tokens may be IngredientToken objects or plain strings.
    """
    count = 0
    for t in tokens:
        raw_text = t.raw if hasattr(t, "raw") else (t.name if hasattr(t, "name") else str(t))
        if re.search(r"[a-zA-Z]", raw_text):
            count += 1
    return count


def is_valid_prediction(pred: NovaPrediction) -> bool:
    """
    Validate that NovaPrediction has valid numerical probabilities summing to ~1.0,
    and no NaN/Inf in confidence or margin.
    """
    if pred is None:
        return False
    if math.isnan(pred.confidence) or math.isinf(pred.confidence):
        return False
    if math.isnan(pred.margin) or math.isinf(pred.margin):
        return False
    if not pred.probs:
        return False

    probs_vals = list(pred.probs.values())
    for v in probs_vals:
        if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            return False

    total = sum(probs_vals)
    # Probs must sum to approximately 1.0 (±0.05)
    if not (0.95 <= total <= 1.05):
        return False

    return True


def check_gate(
    pred: NovaPrediction | None = None,
    rule_score: int = 0,
    ml_score: int | None = None,
    kb_coverage: float = 1.0,
    tokens: list[Any] | None = None,
    model_status: str = "ready",
    error: Exception | str | None = None,
    force_mode: str = "auto",
    settings_obj: Settings | None = None,
) -> str | None:
    """
    Check fallback conditions 0 to 8 in order per ARCHITECTURE §7.3.
    Returns None if ML prediction is accepted, or a reason code string.
    """
    cfg = settings_obj if settings_obj is not None else default_settings

    # Forced rules check
    if force_mode == "rules" or error == "forced_rules":
        return "forced_rules"

    # Check 0: ML disabled
    if not cfg.ml_enabled or model_status == "disabled" or error == "ml_disabled":
        return "ml_disabled"

    # Check 1: Model loading
    if model_status == "loading" or isinstance(error, ModelNotReady) or error == "model_loading":
        return "model_loading"

    # Check 2: Model error
    if model_status == "error" or isinstance(error, ModelError) or error == "model_error":
        return "model_error"

    # Check 3: Timeout
    if (
        isinstance(error, (TimeoutError, concurrent.futures.TimeoutError))
        or error == "model_timeout"
    ):
        return "model_timeout"

    # Any other unhandled exception in predict
    if isinstance(error, Exception):
        return "model_error"

    # Check 3a: Unsupported language (fewer than 2 Latin tokens and ML_HINDI_SUPPORTED=false)
    if tokens is not None and not cfg.ml_hindi_supported:
        latin_count = count_latin_tokens(tokens)
        if latin_count < 2:
            return "unsupported_language"

    if pred is None:
        return "model_error"

    # Check for NaN probabilities or not summing to ~1
    if not is_valid_prediction(pred):
        return "model_error"

    # Check 4: Low confidence (< ML_MIN_CONFIDENCE, default 0.60)
    if pred.confidence < cfg.ml_min_confidence:
        return "low_confidence"

    # Check 5: Top class is NOVA 2 and confidence < ML_NOVA2_MIN_CONFIDENCE (default 0.80)
    if pred.top == 2 and pred.confidence < cfg.ml_nova2_min_confidence:
        return "weak_class_uncertain"

    # Check 6: Small margin (top1 - top2 < ML_MIN_MARGIN, default 0.15)
    if pred.margin < cfg.ml_min_margin:
        return "ambiguous_prediction"

    # Checks 7 & 8: Asymmetric disagreement checks (only when kb_coverage >= 0.60)
    if kb_coverage >= 0.60 and ml_score is not None:
        # Check 7: Optimistic gap (ml_score - rule_score > ML_MAX_OPTIMISTIC_GAP, default 25)
        if ml_score - rule_score > cfg.ml_max_optimistic_gap:
            return "ml_rule_disagreement"

        # Check 8: Pessimistic gap (rule_score - ml_score > ML_MAX_PESSIMISTIC_GAP, default 45)
        if rule_score - ml_score > cfg.ml_max_pessimistic_gap:
            return "ml_rule_disagreement"

    return None


check = check_gate
