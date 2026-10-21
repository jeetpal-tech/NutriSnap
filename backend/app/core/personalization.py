"""
personalization.py - Health condition profile multipliers (ARCHITECTURE §6.2, §8).

Conditions supported:
  - diabetes
  - hypertension
  - high_cholesterol

Multipliers are defined in category_rules.json (never hard-coded):
  diabetes:
    added_sugar: 1.5
    refined_flour: 1.5
    ultra_processing_marker: 1.5
  hypertension:
    sodium_source: 1.5
    flavour_enhancer: 1.5
    preservative: 1.5
  high_cholesterol:
    saturated_fat_source: 1.5
    trans_fat_source: 1.5

Multipliers stack multiplicatively across active conditions.
Personalization modifies the penalty term for flagged ingredients, never ML probabilities.
"""
from __future__ import annotations

from typing import Any


def get_profile_multiplier(
    flag: str,
    conditions: list[str] | None,
    rules_config: dict[str, Any],
) -> float:
    """
    Compute the composite profile multiplier for a single flag across active conditions.
    Returns 1.0 if no conditions are active or no condition targets this flag.
    """
    if not conditions:
        return 1.0

    profile_map = rules_config.get("profile_multipliers", {})
    mult = 1.0

    for condition in conditions:
        cond_flags = profile_map.get(condition, {})
        if flag in cond_flags:
            mult *= float(cond_flags[flag])

    return mult


def get_profile_effects(
    conditions: list[str] | None,
    matched_flags: set[str],
    rules_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Generate the list of profile effects applied to the current product's flags.
    Only includes flags that are actually present in the ingredient list.

    Returns
    -------
    list[dict]
        Each dict has shape {"condition": str, "flag": str, "multiplier": float}
    """
    if not conditions:
        return []

    profile_map = rules_config.get("profile_multipliers", {})
    effects: list[dict[str, Any]] = []

    for condition in conditions:
        cond_flags = profile_map.get(condition, {})
        for flag, mult in cond_flags.items():
            if flag in matched_flags:
                effects.append({
                    "condition": condition,
                    "flag": flag,
                    "multiplier": float(mult),
                })

    return effects
