"""
scoring.py - Pure function combine_ml for ML-assisted scoring (ARCHITECTURE §6.4).

Formulas:
  p        = [p1, p2, p3, p4]                       # NOVA class probabilities
  base_ml  = sum_k p[k] * nova_base[k]             # e.g. 1: 90, 2: 75, 3: 60, 4: 35
  score_ml = clamp(round(base_ml - ml_penalty_scale * penalty + bonus), 0, 100)
  score_ml = apply_safety_caps(score_ml)

No model inference code belongs here.
"""
from __future__ import annotations

from typing import Any

from app.core.rules import apply_safety_caps


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

    Parameters
    ----------
    probs : dict[int, float] | list[float]
        Probabilities for NOVA groups 1, 2, 3, 4.
    penalty : float
        Final capped penalty computed by the rule engine.
    bonus : float
        Final capped bonus computed by the rule engine.
    rules_config : dict
        category_rules.json configuration.
    matched_flags_with_pos : list[tuple[str, int]] | None
        Matched (flag, position) pairs for applying safety caps.

    Returns
    -------
    tuple[int, list[dict]]
        (score_ml clamped to 0..100, caps_applied list)
    """
    nova_base = rules_config.get("nova_base", {"1": 90, "2": 75, "3": 60, "4": 35})
    ml_penalty_scale = float(rules_config.get("ml_penalty_scale", 0.6))

    # Normalize probs to dict {1: p1, 2: p2, 3: p3, 4: p4}
    if isinstance(probs, list):
        # assume 0-indexed or 1-indexed length 4
        p_dict = {i + 1: float(probs[i]) for i in range(min(4, len(probs)))}
    else:
        p_dict = {int(k): float(v) for k, v in probs.items()}

    # Calculate ML base
    base_ml = sum(p_dict.get(k, 0.0) * float(nova_base.get(str(k), 0.0)) for k in (1, 2, 3, 4))

    # Score calculation
    raw_score = round(base_ml - (ml_penalty_scale * penalty) + bonus)
    score_ml = max(0, min(100, int(raw_score)))

    # Apply safety caps
    caps_applied: list[dict[str, Any]] = []
    if matched_flags_with_pos:
        score_ml, caps_applied = apply_safety_caps(score_ml, matched_flags_with_pos, rules_config)

    return score_ml, caps_applied
