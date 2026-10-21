"""
test_rules.py - Comprehensive tests for the NutriSnap rule scoring engine (M2).

Covers:
  - Each of the 12 flag penalties
  - Position multiplier boundaries (3 vs 4, 6 vs 7) and non-weighted flags
  - Sugar-splitting extra penalty (1 sugar vs 2 distinct sugars vs duplicate)
  - Deduplication by kb_id at smallest position
  - Penalty cap (70)
  - Bonus cap (10)
  - Safety caps: trans_fat_source and added_sugar at position 1
  - Each profile multiplier and profile_effects reporting
  - Determinism
  - Band thresholds (39, 40, 69, 70)
  - Pure combine_ml function (ARCHITECTURE §6.4)
"""
from __future__ import annotations

import pytest

from app.core.matcher import MatchResult
from app.core.normalizer import NormalizedToken, normalize
from app.core.parser import IngredientToken, parse
from app.core.personalization import get_profile_effects, get_profile_multiplier
from app.core.rules import (
    RuleScoreResult,
    apply_safety_caps,
    calculate_rule_score,
    get_position_multiplier,
    score_band,
)
from app.core.scoring import combine_ml


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_match(
    position: int,
    kb_id: str | None,
    flag: str | None,
    canonical: str | None = None,
    raw: str = "item",
) -> tuple[IngredientToken, MatchResult]:
    token = IngredientToken(
        position=position,
        raw=raw,
        name=canonical or raw,
        sub_text=None,
        percent=None,
        ins_codes=[],
    )
    match = MatchResult(
        position=position,
        raw=raw,
        name=canonical or raw,
        matched=bool(kb_id),
        kb_id=kb_id,
        canonical=canonical or raw,
        flag=flag,
        entry={"primary_flag": flag, "canonical": canonical} if kb_id else None,
        match_method="exact_alias" if kb_id else "unmatched",
    )
    return token, match


def score_items(items, kb, conditions=None) -> RuleScoreResult:
    tokens = [t for t, _ in items]
    matches = [m for _, m in items]
    return calculate_rule_score(matches, tokens, kb.rules, conditions)


# ── Flag penalties ─────────────────────────────────────────────────────────────

class TestFlagPenalties:
    """Verify each penalty flag at position 4 (where position multiplier is 1.0)."""

    @pytest.mark.parametrize(
        "flag,expected_penalty",
        [
            ("added_sugar", 12.0),
            ("refined_flour", 8.0),
            ("saturated_fat_source", 8.0),
            ("trans_fat_source", 20.0),
            ("sodium_source", 3.0),
            ("flavour_enhancer", 6.0),
            ("preservative", 5.0),
            ("artificial_sweetener", 6.0),
            ("synthetic_colour", 5.0),
            ("emulsifier_stabiliser", 3.0),
            ("flavour_additive", 3.0),
            ("ultra_processing_marker", 6.0),
        ],
    )
    def test_single_flag_penalty_at_pos_4(self, kb, flag, expected_penalty):
        # 1 ingredient at pos 4 (pos_mult=1.0)
        items = [make_match(4, f"id_{flag}", flag, canonical=flag)]
        res = score_items(items, kb)
        assert res.penalty == expected_penalty
        assert res.base == 85.0  # <= 8 items, 0 unflagged additives
        expected_score = round(85 - expected_penalty)
        # Note: trans_fat_source triggers safety cap 69 if score > 69
        if flag == "trans_fat_source":
            assert res.score == min(69, expected_score)
        else:
            assert res.score == expected_score


# ── Position multipliers ───────────────────────────────────────────────────────

class TestPositionMultipliers:
    def test_position_weighted_boundary_3_vs_4(self, kb):
        """added_sugar is position weighted: pos 3 -> x1.5 (18), pos 4 -> x1.0 (12)."""
        items_pos3 = [make_match(3, "sugar", "added_sugar")]
        items_pos4 = [make_match(4, "sugar", "added_sugar")]

        res3 = score_items(items_pos3, kb)
        res4 = score_items(items_pos4, kb)

        assert res3.penalty == 18.0  # 12 * 1.5
        assert res4.penalty == 12.0  # 12 * 1.0

    def test_position_weighted_boundary_6_vs_7(self, kb):
        """added_sugar: pos 6 -> x1.0 (12), pos 7 -> x0.7 (8.4)."""
        items_pos6 = [make_match(6, "sugar", "added_sugar")]
        items_pos7 = [make_match(7, "sugar", "added_sugar")]

        res6 = score_items(items_pos6, kb)
        res7 = score_items(items_pos7, kb)

        assert res6.penalty == 12.0  # 12 * 1.0
        assert res7.penalty == pytest.approx(8.4, abs=0.01)  # 12 * 0.7

    def test_unweighted_flag_ignores_position(self, kb):
        """trans_fat_source is position_weighted: false, so pos 1, 4, 7 all have mult 1.0 (20 pts)."""
        for pos in (1, 4, 7):
            items = [make_match(pos, "vanaspati", "trans_fat_source")]
            res = score_items(items, kb)
            assert res.penalty == 20.0


# ── Deduplication ──────────────────────────────────────────────────────────────

class TestDeduplication:
    def test_palm_oil_twice_counts_once(self, kb):
        """Palm oil at pos 1 and pos 5: counted once at pos 1."""
        items = [
            make_match(1, "palm_oil", "saturated_fat_source", canonical="Palm oil"),
            make_match(5, "palm_oil", "saturated_fat_source", canonical="Palmolein"),
        ]
        res = score_items(items, kb)
        # Saturated fat at pos 1 is 8 * 1.5 = 12.0. Second is deduplicated (0 pts).
        assert res.penalty == 12.0
        assert len(res.scored_ingredients) == 2
        assert res.scored_ingredients[0].deduplicated is False
        assert res.scored_ingredients[0].points == -12.0
        assert res.scored_ingredients[1].deduplicated is True
        assert res.scored_ingredients[1].points == 0.0

    def test_duplicate_does_not_trigger_sugar_splitting(self, kb):
        """Same sugar ingredient listed twice (e.g. bilingual label) is 1 distinct sugar."""
        items = [
            make_match(2, "sugar", "added_sugar", canonical="Sugar"),
            make_match(5, "sugar", "added_sugar", canonical="Chini"),
        ]
        res = score_items(items, kb)
        assert res.sugar_splitting_applied is False


# ── Sugar splitting ────────────────────────────────────────────────────────────

class TestSugarSplitting:
    def test_single_sugar_no_splitting_penalty(self, kb):
        items = [make_match(4, "sugar", "added_sugar")]
        res = score_items(items, kb)
        assert res.sugar_splitting_applied is False
        assert res.penalty == 12.0

    def test_two_distinct_sugars_adds_4_extra_penalty(self, kb):
        """Sugar (12) + Dextrose (12) at pos 4 and 5 + 4 extra = 28."""
        items = [
            make_match(4, "sugar", "added_sugar"),
            make_match(5, "dextrose", "added_sugar"),
        ]
        res = score_items(items, kb)
        assert res.sugar_splitting_applied is True
        # 12 (pos 4) + 12 (pos 5) + 4 extra = 28.0
        assert res.penalty == 28.0


# ── Caps ───────────────────────────────────────────────────────────────────────

class TestCaps:
    def test_penalty_cap_70(self, kb):
        """Total penalties exceeding 70 are capped at 70."""
        # 4 trans_fat_source items (4 * 20 = 80)
        items = [
            make_match(1, "trans1", "trans_fat_source"),
            make_match(2, "trans2", "trans_fat_source"),
            make_match(3, "trans3", "trans_fat_source"),
            make_match(4, "trans4", "trans_fat_source"),
        ]
        res = score_items(items, kb)
        assert res.penalty_before_cap == 80.0
        assert res.penalty == 70.0
        # base=85, penalty=70 -> 15. Safety cap 69 doesn't lower 15.
        assert res.score == 15

    def test_bonus_cap_10(self, kb):
        """Sum of bonus flags capped at 10."""
        # 3 whole_grain items (3 * 4 = 12) -> capped at 10
        items = [
            make_match(1, "oats", "whole_grain_or_fibre"),
            make_match(2, "ragi", "whole_grain_or_fibre"),
            make_match(3, "bajra", "whole_grain_or_fibre"),
        ]
        res = score_items(items, kb)
        assert res.bonus == 10.0


# ── Safety caps ────────────────────────────────────────────────────────────────

class TestSafetyCaps:
    def test_trans_fat_safety_cap_limits_score_to_69(self, kb):
        """Even if score would be 85 - 20 = 65, what if bonus puts it above 69?"""
        # Base 85 - 20 (trans fat) + 10 (bonus) = 75 -> safety cap brings to 69
        items = [
            make_match(1, "oats", "whole_grain_or_fibre"),      # +4
            make_match(2, "ragi", "whole_grain_or_fibre"),      # +4
            make_match(3, "almonds", "legume_nut_seed"),        # +3 (bonus sum = 10)
            make_match(4, "vanaspati", "trans_fat_source"),     # -20
        ]
        res = score_items(items, kb)
        # Raw score: 85 - 20 + 10 = 75
        assert res.score == 69
        assert any("trans_fat_source" in cap["reason"] for cap in res.caps_applied)

    def test_sugar_at_pos_1_safety_cap_limits_score_to_69(self, kb):
        """Sugar as first ingredient limits score to at most 69."""
        # Base 85 - 18 (sugar pos 1 = 12*1.5) + 10 (bonus) = 77 -> capped at 69
        items = [
            make_match(1, "sugar", "added_sugar"),
            make_match(2, "oats", "whole_grain_or_fibre"),
            make_match(3, "ragi", "whole_grain_or_fibre"),
            make_match(4, "almonds", "legume_nut_seed"),
        ]
        res = score_items(items, kb)
        assert res.score == 69
        assert any("added_sugar" in cap["reason"] for cap in res.caps_applied)

    def test_sugar_at_pos_2_does_not_trigger_position_cap(self, kb):
        """Sugar at pos 2 does not trigger the pos <= 1 cap."""
        items = [
            make_match(1, "oats", "whole_grain_or_fibre"),
            make_match(2, "sugar", "added_sugar"),
            make_match(3, "ragi", "whole_grain_or_fibre"),
            make_match(4, "almonds", "legume_nut_seed"),
        ]
        res = score_items(items, kb)
        # Sugar at pos 2 is penalized (12*1.5=18), bonus is +10 -> 85 - 18 + 10 = 77
        assert res.score == 77
        assert len(res.caps_applied) == 0


# ── Profile multipliers ────────────────────────────────────────────────────────

class TestProfileMultipliers:
    def test_diabetes_profile(self, kb):
        """Diabetes scales added_sugar and refined_flour by 1.5."""
        items = [make_match(4, "sugar", "added_sugar")]
        res_default = score_items(items, kb, conditions=None)
        res_diab = score_items(items, kb, conditions=["diabetes"])

        assert res_default.penalty == 12.0
        assert res_diab.penalty == 18.0  # 12.0 * 1.5
        assert len(res_diab.profile_effects) == 1
        assert res_diab.profile_effects[0]["condition"] == "diabetes"
        assert res_diab.profile_effects[0]["multiplier"] == 1.5

    def test_hypertension_profile(self, kb):
        """Hypertension scales sodium_source, flavour_enhancer, preservative by 1.5."""
        items = [make_match(4, "salt", "sodium_source")]
        res_hyp = score_items(items, kb, conditions=["hypertension"])
        assert res_hyp.penalty == 4.5  # 3.0 * 1.5

    def test_high_cholesterol_profile(self, kb):
        """High cholesterol scales saturated_fat_source and trans_fat_source by 1.5."""
        items = [make_match(4, "palm_oil", "saturated_fat_source")]
        res_chol = score_items(items, kb, conditions=["high_cholesterol"])
        assert res_chol.penalty == 12.0  # 8.0 * 1.5


# ── Band thresholds & determinism ──────────────────────────────────────────────

class TestBandsAndDeterminism:
    def test_band_thresholds(self, kb):
        assert score_band(39, kb.rules) == "High Risk"
        assert score_band(40, kb.rules) == "Moderate Risk"
        assert score_band(69, kb.rules) == "Moderate Risk"
        assert score_band(70, kb.rules) == "Low Risk"

    def test_determinism_across_multiple_runs(self, kb):
        items = [
            make_match(1, "refined_wheat_flour", "refined_flour"),
            make_match(2, "sugar", "added_sugar"),
            make_match(3, "palm_oil", "saturated_fat_source"),
            make_match(4, "salt", "sodium_source"),
        ]
        first = score_items(items, kb)
        for _ in range(10):
            again = score_items(items, kb)
            assert again.score == first.score
            assert again.penalty == first.penalty
            assert again.band == first.band


# ── Pure combine_ml function ───────────────────────────────────────────────────

class TestCombineML:
    def test_pure_combine_ml(self, kb):
        """
        base_ml = p1*90 + p2*75 + p3*60 + p4*35
        For p = [0, 0, 0, 1.0] -> base_ml = 35
        penalty = 10, bonus = 0
        ml_penalty_scale = 0.6
        score = 35 - 0.6*10 = 29
        """
        probs = {1: 0.0, 2: 0.0, 3: 0.0, 4: 1.0}
        score, caps = combine_ml(probs, penalty=10.0, bonus=0.0, rules_config=kb.rules)
        assert score == 29
        assert caps == []

    def test_combine_ml_respects_safety_caps(self, kb):
        """Trans fat presence caps ML score at 69 even with high base."""
        probs = {1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0}  # base 90
        score, caps = combine_ml(
            probs,
            penalty=0.0,
            bonus=0.0,
            rules_config=kb.rules,
            matched_flags_with_pos=[("trans_fat_source", 2)],
        )
        assert score == 69
        assert len(caps) == 1
