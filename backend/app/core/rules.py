"""
rules.py - NutriSnap rule-based scoring engine (ARCHITECTURE §6.1, §6.2, §6.3, §6.5).

All constants are loaded from category_rules.json (never hard-coded):
  - Base score: 85 - complexity penalty - unflagged additives penalty
  - Ingredient penalties: flag penalty * position multiplier * profile multiplier
  - Deduplication: each kb_id counted once at its smallest position
  - Sugar splitting penalty: extra penalty if >= 2 distinct added_sugar ingredients
  - Penalty cap: min(penalty, 70)
  - Bonus: whole_grain_or_fibre (4), legume_nut_seed (3), capped at 10
  - Safety caps: trans_fat_source (max 69), added_sugar at pos 1 (max 69)
  - Bands: 0-39 High Risk, 40-69 Moderate Risk, 70-100 Low Risk
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.matcher import MatchResult
from app.core.parser import IngredientToken
from app.core.personalization import get_profile_effects, get_profile_multiplier


@dataclass
class ScoredIngredient:
    """Detailed scoring output for a single ingredient token."""
    position: int
    raw: str
    name: str
    matched: bool
    kb_id: str | None
    canonical: str | None
    flag: str | None
    points: float
    deduplicated: bool = False
    explanation: str | None = None
    source: Any | None = None
    verified: bool = False


@dataclass
class RuleScoreResult:
    """Output of the rule scoring engine."""
    score: int
    band: str
    base: float
    complexity_penalty: float
    unflagged_additive_penalty: float
    penalty_before_cap: float
    penalty: float
    bonus: float
    sugar_splitting_applied: bool
    caps_applied: list[dict[str, Any]] = field(default_factory=list)
    profile_effects: list[dict[str, Any]] = field(default_factory=list)
    scored_ingredients: list[ScoredIngredient] = field(default_factory=list)
    flags_summary: list[dict[str, Any]] = field(default_factory=list)


def get_position_multiplier(
    position: int,
    flag: str,
    rules_config: dict[str, Any],
) -> float:
    """
    Returns position multiplier for a given position and flag.
    Only applies if flag has position_weighted: true in rules_config['flags'].
    """
    flag_cfg = rules_config.get("flags", {}).get(flag, {})
    if not flag_cfg.get("position_weighted", False):
        return 1.0

    pos_mult_map = rules_config.get("position_multiplier", {})
    if position <= 3:
        return float(pos_mult_map.get("1-3", 1.5))
    elif position <= 6:
        return float(pos_mult_map.get("4-6", 1.0))
    else:
        return float(pos_mult_map.get("7+", 0.7))


def score_band(score: int, rules_config: dict[str, Any]) -> str:
    """Map integer score 0-100 to risk band string."""
    bands = rules_config.get("bands", {})
    high_max = bands.get("high_risk_max", 39)
    mod_max = bands.get("moderate_max", 69)

    if score <= high_max:
        return "High Risk"
    elif score <= mod_max:
        return "Moderate Risk"
    else:
        return "Low Risk"


def apply_safety_caps(
    score: int,
    matched_flags_with_pos: list[tuple[str, int]],
    rules_config: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    """
    Apply safety caps defined in rules_config['safety_caps'].
    A cap can only lower or keep the score identical, never raise it.
    """
    caps_applied: list[dict[str, Any]] = []
    final_score = score

    safety_caps = rules_config.get("safety_caps", [])
    for cap in safety_caps:
        # Case 1: if_flag_present
        if "if_flag_present" in cap:
            target_flag = cap["if_flag_present"]
            max_score = int(cap["max_score"])
            if any(f == target_flag for f, _ in matched_flags_with_pos):
                if final_score > max_score:
                    final_score = max_score
                    caps_applied.append({
                        "reason": f"Flag '{target_flag}' present limits score to {max_score}",
                        "max_score": max_score,
                    })

        # Case 2: if_flag_at_position_le
        elif "if_flag_at_position_le" in cap:
            cond = cap["if_flag_at_position_le"]
            target_flag = cond["flag"]
            target_pos = cond["position"]
            max_score = int(cap["max_score"])
            if any(f == target_flag and pos <= target_pos for f, pos in matched_flags_with_pos):
                if final_score > max_score:
                    final_score = max_score
                    caps_applied.append({
                        "reason": f"Flag '{target_flag}' at position <= {target_pos} limits score to {max_score}",
                        "max_score": max_score,
                    })

    return final_score, caps_applied


def calculate_rule_score(
    matches: list[MatchResult],
    tokens: list[IngredientToken],
    rules_config: dict[str, Any],
    conditions: list[str] | None = None,
) -> RuleScoreResult:
    """
    Score matched ingredients using the rule engine per ARCHITECTURE §6.3.

    Parameters
    ----------
    matches : list[MatchResult]
        Matches from matcher.py.
    tokens : list[IngredientToken]
        Tokens from parser.py.
    rules_config : dict
        category_rules.json dictionary.
    conditions : list[str] | None
        Active health profile conditions.
    """
    rule_base_cfg = rules_config.get("rule_base", {})
    start_base = rule_base_cfg.get("start", 85)
    free_count = rule_base_cfg.get("free_ingredient_count", 8)
    per_extra = rule_base_cfg.get("per_extra_ingredient", 1)
    complexity_max = rule_base_cfg.get("complexity_max", 10)
    per_unflagged = rule_base_cfg.get("per_unflagged_additive", 2)
    unflagged_max = rule_base_cfg.get("unflagged_additive_max", 10)

    flags_cfg = rules_config.get("flags", {})
    bonus_cfg = rules_config.get("bonus", {})

    # 1. Complexity penalty
    n_tokens = len(tokens)
    extra_ingredients = max(0, n_tokens - free_count)
    complexity_penalty = min(complexity_max, extra_ingredients * per_extra)

    # 2. Unflagged additives penalty
    # Find INS codes whose matched entry does NOT have an additive penalty flag
    unflagged_ins: set[str] = set()
    for token, match in zip(tokens, matches):
        if token.ins_codes:
            # If the token didn't match or matched a non-penalty flag, count its INS codes
            if not match.matched or match.flag not in flags_cfg:
                for code in token.ins_codes:
                    unflagged_ins.add(code)
    unflagged_additive_penalty = min(unflagged_max, per_unflagged * len(unflagged_ins))

    # Base score
    base = start_base - complexity_penalty - unflagged_additive_penalty

    # 3. Deduplication by kb_id at smallest position (ARCHITECTURE §5.3 / §6.3)
    seen_kb_ids: set[str] = set()
    deduped_matches: list[MatchResult] = []
    scored_ingredients: list[ScoredIngredient] = []

    # Sort by position ascending to guarantee smallest position is preserved
    sorted_matches = sorted(matches, key=lambda m: m.position)

    for m in sorted_matches:
        if m.matched and m.kb_id:
            if m.kb_id in seen_kb_ids:
                # Duplicate — keep for display with 0 points
                scored_ingredients.append(ScoredIngredient(
                    position=m.position,
                    raw=m.raw,
                    name=m.name,
                    matched=True,
                    kb_id=m.kb_id,
                    canonical=m.canonical,
                    flag=m.flag,
                    points=0.0,
                    deduplicated=True,
                    explanation=m.entry.get("explanation") if m.entry else None,
                    source=m.entry.get("source") if m.entry else None,
                    verified=m.entry.get("verified", False) if m.entry else False,
                ))
                continue
            seen_kb_ids.add(m.kb_id)
            deduped_matches.append(m)
        else:
            # Unmatched ingredient
            scored_ingredients.append(ScoredIngredient(
                position=m.position,
                raw=m.raw,
                name=m.name,
                matched=False,
                kb_id=None,
                canonical=None,
                flag=None,
                points=0.0,
                deduplicated=False,
            ))

    # 4. Calculate penalties and bonuses on deduplicated matches
    penalty_sum = 0.0
    bonus_sum = 0.0
    distinct_sugars: set[str] = set()
    matched_flags_set: set[str] = set()
    matched_flags_with_pos: list[tuple[str, int]] = []

    for m in deduped_matches:
        flag = m.flag
        pts = 0.0

        if flag:
            matched_flags_set.add(flag)
            matched_flags_with_pos.append((flag, m.position))

            # Penalty flag
            if flag in flags_cfg:
                base_pen = float(flags_cfg[flag]["penalty"])
                pos_mult = get_position_multiplier(m.position, flag, rules_config)
                prof_mult = get_profile_multiplier(flag, conditions, rules_config)
                item_penalty = base_pen * pos_mult * prof_mult
                pts = -item_penalty
                penalty_sum += item_penalty

                if flag == "added_sugar" and m.kb_id:
                    distinct_sugars.add(m.kb_id)

            # Bonus flag
            elif flag in bonus_cfg and flag != "cap":
                bonus_val = float(bonus_cfg[flag])
                pts = bonus_val
                bonus_sum += bonus_val

        scored_ingredients.append(ScoredIngredient(
            position=m.position,
            raw=m.raw,
            name=m.name,
            matched=True,
            kb_id=m.kb_id,
            canonical=m.canonical,
            flag=m.flag,
            points=round(pts, 1),
            deduplicated=False,
            explanation=m.entry.get("explanation") if m.entry else None,
            source=m.entry.get("source") if m.entry else None,
            verified=m.entry.get("verified", False) if m.entry else False,
        ))

    # Re-sort scored_ingredients by original position
    scored_ingredients.sort(key=lambda s: s.position)

    # 5. Sugar splitting penalty
    sugar_splitting_applied = False
    if len(distinct_sugars) >= 2:
        split_pen = float(rules_config.get("sugar_splitting_extra_penalty", 4))
        penalty_sum += split_pen
        sugar_splitting_applied = True

    # 6. Caps on penalty and bonus
    penalty_cap = float(rules_config.get("penalty_cap", 70))
    final_penalty = min(penalty_sum, penalty_cap)

    bonus_cap = float(bonus_cfg.get("cap", 10))
    final_bonus = min(bonus_sum, bonus_cap)

    # 7. Final raw rule score
    raw_score = round(base - final_penalty + final_bonus)
    clamped_score = max(0, min(100, int(raw_score)))

    # 8. Safety caps
    final_score, caps_applied = apply_safety_caps(
        clamped_score,
        matched_flags_with_pos,
        rules_config,
    )

    # 9. Risk band
    band = score_band(final_score, rules_config)

    # 10. Profile effects
    profile_effects = get_profile_effects(conditions, matched_flags_set, rules_config)

    # 11. Flag summary
    flag_summaries: list[dict[str, Any]] = []
    for f in sorted(matched_flags_set):
        # Determine severity per ARCHITECTURE §9.2:
        # high if |points| >= 12, medium if >= 5, else low
        flag_pen = float(flags_cfg.get(f, {}).get("penalty", 0))
        if flag_pen >= 12:
            severity = "high"
        elif flag_pen >= 5:
            severity = "medium"
        else:
            severity = "low"

        flag_summaries.append({
            "flag": f,
            "label": f.replace("_", " ").capitalize(),
            "severity": severity,
        })

    return RuleScoreResult(
        score=final_score,
        band=band,
        base=round(base, 1),
        complexity_penalty=round(complexity_penalty, 1),
        unflagged_additive_penalty=round(unflagged_additive_penalty, 1),
        penalty_before_cap=round(penalty_sum, 1),
        penalty=round(final_penalty, 1),
        bonus=round(final_bonus, 1),
        sugar_splitting_applied=sugar_splitting_applied,
        caps_applied=caps_applied,
        profile_effects=profile_effects,
        scored_ingredients=scored_ingredients,
        flags_summary=flag_summaries,
    )
