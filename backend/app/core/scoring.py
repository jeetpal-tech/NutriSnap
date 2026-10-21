"""
scoring.py - ML combiner and orchestrator for NutriSnap scoring lifecycle (ARCHITECTURE §4, §6.4, §9.2).
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Literal

from app.config import settings
from app.core.gate import check_gate, count_latin_tokens, is_valid_prediction
from app.core.knowledge_base import KnowledgeBase
from app.core.matcher import MatchResult, looks_like_food, match_tokens
from app.core.ml.base import ModelError, ModelNotReady, NovaModel, NovaPrediction
from app.core.ml.manager import get_model
from app.core.normalizer import normalize
from app.core.parser import IngredientToken, parse
from app.core.rules import (
    RuleScoreResult,
    ScoredIngredient,
    apply_safety_caps,
    calculate_rule_score,
    score_band,
)
from app.schemas import (
    AnalyzeResponse,
    FlagSummary,
    IngredientResult,
    LanguageResult,
    NovaBadge,
    NovaResult,
    NutriscoreResult,
    ProfileEffect,
    ProfileRequest,
    SafetyCapApplied,
    SwapTip,
)

logger = logging.getLogger(__name__)

# Single-worker ThreadPoolExecutor for isolated ML inference with timeout (ARCHITECTURE §7.4)
_inference_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="nova-inference",
)


def combine_ml(
    probs: dict[int, float] | list[float],
    penalty: float,
    bonus: float,
    rules_config: dict[str, Any],
    matched_flags_with_pos: list[tuple[str, int]] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """
    Pure function computing the ML-assisted score from NOVA class probabilities,
    ingredient penalties and bonuses, per ARCHITECTURE §6.4.
    """
    nova_base = rules_config.get("nova_base", {"1": 90, "2": 75, "3": 60, "4": 35})
    ml_penalty_scale = float(rules_config.get("ml_penalty_scale", 0.6))

    if isinstance(probs, list):
        p_dict = {i + 1: float(probs[i]) for i in range(min(4, len(probs)))}
    else:
        p_dict = {int(k): float(v) for k, v in probs.items()}

    base_ml = sum(p_dict.get(k, 0.0) * float(nova_base.get(str(k), 0.0)) for k in (1, 2, 3, 4))

    raw_score = round(base_ml - (ml_penalty_scale * penalty) + bonus)
    score_ml = max(0, min(100, int(raw_score)))

    caps_applied: list[dict[str, Any]] = []
    if matched_flags_with_pos:
        score_ml, caps_applied = apply_safety_caps(score_ml, matched_flags_with_pos, rules_config)

    return score_ml, caps_applied


def _map_ingredient_risk(
    ing: ScoredIngredient,
) -> Literal["low", "medium", "high", "neutral", "unknown"]:
    """Map a scored ingredient to its risk level per ARCHITECTURE §9.2."""
    if not ing.matched:
        return "unknown"
    if not ing.flag:
        return "neutral"
    if ing.points > 0:
        return "low"
    abs_pts = abs(ing.points)
    if abs_pts >= 12:
        return "high"
    if abs_pts >= 5:
        return "medium"
    return "low"


def _build_ingredients_list(
    scored_ingredients: list[ScoredIngredient],
) -> list[IngredientResult]:
    """Format scored ingredients into schema IngredientResult objects."""
    results: list[IngredientResult] = []
    for ing in scored_ingredients:
        results.append(
            IngredientResult(
                position=ing.position,
                raw=ing.raw,
                name=ing.name,
                matched=ing.matched,
                kb_id=ing.kb_id,
                canonical=ing.canonical,
                flag=ing.flag,
                risk=_map_ingredient_risk(ing),
                points=ing.points,
                explanation=ing.explanation,
                source=ing.source,
                verified=ing.verified,
            )
        )
    return results


def _build_swap_tips(matches: list[MatchResult]) -> list[SwapTip]:
    """Extract swap tips for distinct matched penalty flags."""
    swap_tips: list[SwapTip] = []
    seen_flags: set[str] = set()
    for m in matches:
        if m.matched and m.flag and m.flag not in seen_flags:
            seen_flags.add(m.flag)
            tip = m.entry.get("swap_tip") if m.entry else None
            swap_tips.append(SwapTip(flag=m.flag, tip=tip))
    return swap_tips


def _build_response_payload(
    status: Literal["ok"],
    score: int,
    band: Literal["Low Risk", "Moderate Risk", "High Risk"],
    scoring_method: Literal["ml_assisted", "rule_based"],
    fallback_reason: str | None,
    rule_score: int,
    ml_score: int | None,
    pred: NovaPrediction | None,
    kb_coverage: float,
    rule_result: RuleScoreResult,
    caps_applied_dicts: list[dict[str, Any]],
    matches: list[MatchResult],
    tokens: list[IngredientToken],
) -> AnalyzeResponse:
    """Construct full AnalyzeResponse meeting the exact schema in ARCHITECTURE §9.2."""
    nova_res = None
    if pred is not None:
        nova_res = NovaResult(
            top=pred.top,
            confidence=round(pred.confidence, 4),
            probs={str(k): round(v, 4) for k, v in pred.probs.items()},
            model_id=pred.model_id,
            latency_ms=pred.latency_ms,
        )

    flags_summary = [
        FlagSummary(
            flag=f["flag"],
            label=f["label"],
            severity=f["severity"],
        )
        for f in rule_result.flags_summary
    ]

    profile_effects = [
        ProfileEffect(
            condition=pe["condition"],
            flag=pe["flag"],
            multiplier=pe["multiplier"],
        )
        for pe in rule_result.profile_effects
    ]

    caps_applied = [
        SafetyCapApplied(reason=c["reason"], max_score=c["max_score"])
        for c in caps_applied_dicts
    ]

    warnings: list[str] = []
    if len(tokens) >= 80:
        warnings.append("Ingredient list exceeded 80 tokens; remaining ingredients were truncated.")

    return AnalyzeResponse(
        status="ok",
        score=score,
        band=band,
        scoring_method=scoring_method,
        fallback_reason=fallback_reason,
        rule_score=rule_score,
        ml_score=ml_score,
        nova=nova_res,
        kb_coverage=round(kb_coverage, 2),
        low_coverage_warning=bool(kb_coverage < 0.60),
        nova_badge=NovaBadge(group=None, label=None, source="unavailable", confidence=None, basis=[]),
        nutriscore=NutriscoreResult(status="not_provided"),
        language=LanguageResult(detected="latin", ml_input="full"),
        flags=flags_summary,
        ingredients=_build_ingredients_list(rule_result.scored_ingredients),
        profile_effects=profile_effects,
        caps_applied=caps_applied,
        swap_tips=_build_swap_tips(matches),
        disclaimer="Informational only, not medical advice. NOVA reflects processing level, not toxicity.",
        attribution="Contains information from Open Food Facts (ODbL).",
        warnings=warnings,
    )


def analyze(
    text: str,
    profile: ProfileRequest | dict[str, Any] | None = None,
    force_mode: Literal["auto", "rules"] = "auto",
    kb: KnowledgeBase | None = None,
    model: NovaModel | None = None,
) -> AnalyzeResponse:
    """
    End-to-end analyze orchestrator implementing lifecycle in ARCHITECTURE §4:
      1. validate length 1..4000
      2. parse -> tokens
      3. tokens < 2 or chars < 15 -> insufficient_input
      4. normalize + match -> matches, kb_coverage
      5. kb_coverage < 0.30 and not looks_like_food -> not_food_text
      6. rule = rules.score(matches, profile)
      7. if force_mode == 'rules' or ML disabled -> rule-based result
      8. try ml.predict(text, timeout) -> fallback on exception/timeout
      9. gate.check(pred, rule, kb_coverage) -> fallback if reason
     10. combine_ml(pred, matches, profile) and apply safety caps
     11. return ml_assisted result (or rule-based with transparency)
    """
    # 1. Validation
    if not (1 <= len(text) <= 4000):
        raise ValueError("ingredients_text length must be between 1 and 4000 characters.")

    if kb is None:
        from app.api.routes import _kb
        if _kb is None:
            _kb = KnowledgeBase()
            _kb.load()
        kb = _kb

    if model is None:
        model = get_model()

    # 2. Parse
    tokens = parse(text)

    # 3. Check insufficient_input
    if len(tokens) < 2 or len(text.strip()) < 15:
        return AnalyzeResponse(
            status="insufficient_input",
            message="Please paste at least two ingredients.",
            scoring_method=None,
        )

    # 4. Normalize and match
    norm_tokens = [normalize(t) for t in tokens]
    positions = [t.position for t in tokens]
    matches, kb_coverage = match_tokens(norm_tokens, positions, kb)

    # 5. Check not_food_text
    if kb_coverage < 0.30 and not looks_like_food(matches, norm_tokens, kb):
        return AnalyzeResponse(
            status="not_food_text",
            message="This does not look like an ingredient list.",
            scoring_method=None,
        )

    # 6. Rule score always computed
    conditions: list[str] | None = None
    if profile is not None:
        if isinstance(profile, dict):
            conditions = profile.get("conditions", [])
        elif hasattr(profile, "conditions"):
            conditions = profile.conditions

    rule_result = calculate_rule_score(matches, tokens, kb.rules, conditions=conditions)

    # 7. Pre-inference gate checks (forced_rules, ml_disabled, loading, error, unsupported_language)
    if force_mode == "rules":
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="forced_rules",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    if not settings.ml_enabled or model.status == "disabled" or getattr(model, "is_stub", False):
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="ml_disabled",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    if model.status == "loading":
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_loading",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    if model.status == "error":
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_error",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    # Check 3a: Unsupported language (fewer than 2 Latin tokens and ML_HINDI_SUPPORTED=false)
    if not settings.ml_hindi_supported and count_latin_tokens(tokens) < 2:
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="unsupported_language",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    # 8. ML call with timeout via ThreadPoolExecutor
    pred: NovaPrediction | None = None
    try:
        future = _inference_executor.submit(model.predict, text)
        pred = future.result(timeout=settings.ml_timeout_s)
    except (TimeoutError, concurrent.futures.TimeoutError):
        logger.warning("ML inference exceeded timeout of %.2f seconds.", settings.ml_timeout_s)
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_timeout",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )
    except ModelNotReady:
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_loading",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )
    except ModelError:
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_error",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )
    except Exception as exc:
        logger.exception("ML inference encountered unexpected error: %s", exc)
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_error",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    # 9. Validate prediction values (NaN / Inf / sums to ~1)
    if not is_valid_prediction(pred):
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason="model_error",
            rule_score=rule_result.score,
            ml_score=None,
            pred=None,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    # Compute candidate ML score
    matched_flags_with_pos = [(m.flag, m.position) for m in matches if m.flag]
    ml_score, caps_applied_ml = combine_ml(
        pred.probs,
        penalty=rule_result.penalty,
        bonus=rule_result.bonus,
        rules_config=kb.rules,
        matched_flags_with_pos=matched_flags_with_pos,
    )

    # 10. Fallback gate checks (4..8)
    gate_reason = check_gate(
        pred=pred,
        rule_score=rule_result.score,
        ml_score=ml_score,
        kb_coverage=kb_coverage,
        tokens=tokens,
        model_status=model.status,
        force_mode=force_mode,
        settings_obj=settings,
    )

    if gate_reason is not None:
        # Gate rejected ML — return rule-based result with fallback reason and transparency fields
        return _build_response_payload(
            status="ok",
            score=rule_result.score,
            band=rule_result.band,
            scoring_method="rule_based",
            fallback_reason=gate_reason,
            rule_score=rule_result.score,
            ml_score=ml_score,
            pred=pred,
            kb_coverage=kb_coverage,
            rule_result=rule_result,
            caps_applied_dicts=rule_result.caps_applied,
            matches=matches,
            tokens=tokens,
        )

    # 11. ML accepted!
    ml_band = score_band(ml_score, kb.rules)
    return _build_response_payload(
        status="ok",
        score=ml_score,
        band=ml_band,
        scoring_method="ml_assisted",
        fallback_reason=None,
        rule_score=rule_result.score,
        ml_score=ml_score,
        pred=pred,
        kb_coverage=kb_coverage,
        rule_result=rule_result,
        caps_applied_dicts=caps_applied_ml,
        matches=matches,
        tokens=tokens,
    )
