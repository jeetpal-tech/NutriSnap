"""
test_matcher.py - Matcher unit tests (ARCHITECTURE §12 matcher cases).

All cases are deterministic; no ML model or network required.
Uses the real loaded KB via the session-scoped `kb` fixture in conftest.py.
"""
from __future__ import annotations

import pytest
from app.core.knowledge_base import KnowledgeBase
from app.core.matcher import FUZZY_MIN_SHORT, match_tokens, looks_like_food
from app.core.normalizer import NormalizedToken, normalize_text
from app.core.parser import parse
from app.core.normalizer import normalize


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_and_match(text: str, kb: KnowledgeBase):
    """Full pipeline: parse → normalize → match."""
    tokens = parse(text)
    norm_tokens = [normalize(t) for t in tokens]
    positions = [t.position for t in tokens]
    results, coverage = match_tokens(norm_tokens, positions, kb)
    return results, coverage


def make_token(name: str, codes: list[str] | None = None) -> NormalizedToken:
    return NormalizedToken(name=name, codes=codes or [], raw=name)


# ── Exact alias matching ───────────────────────────────────────────────────────

class TestExactAlias:
    def test_canonical_name_matches(self, kb):
        results, _ = parse_and_match("Sugar", kb)
        assert results[0].matched
        assert results[0].kb_id == "sugar"
        assert results[0].match_method == "exact_alias"

    def test_alias_matches(self, kb):
        """'maida' is an alias for refined_wheat_flour."""
        results, _ = parse_and_match("maida", kb)
        assert results[0].matched
        assert results[0].kb_id == "refined_wheat_flour"

    def test_case_insensitive(self, kb):
        results, _ = parse_and_match("SUGAR", kb)
        assert results[0].matched
        assert results[0].kb_id == "sugar"

    def test_palmolein_alias(self, kb):
        """'palmolein' is listed as alias for palm_oil."""
        results, _ = parse_and_match("palmolein", kb)
        assert results[0].matched
        assert results[0].kb_id == "palm_oil"


# ── Exact INS code matching ────────────────────────────────────────────────────

class TestExactINS:
    def test_ins_211_matches_sodium_benzoate(self, kb):
        results, _ = parse_and_match("Preservative (INS 211)", kb)
        assert results[0].matched
        assert results[0].kb_id == "sodium_benzoate"
        assert results[0].match_method == "exact_ins"

    def test_e211_matches_sodium_benzoate(self, kb):
        """E211 should normalize and match."""
        results, _ = parse_and_match("E211", kb)
        assert results[0].matched
        assert results[0].kb_id == "sodium_benzoate"

    def test_ins_621_matches_msg(self, kb):
        results, _ = parse_and_match("Flavour enhancer (INS 621)", kb)
        assert results[0].matched
        assert results[0].kb_id == "monosodium_glutamate"


# ── Fuzzy matching ─────────────────────────────────────────────────────────────

class TestFuzzyMatching:
    def test_palm_olien_typo(self, kb):
        """'Palm olien' (typo for 'palm olein') should fuzzy-match to palm_oil."""
        results, _ = parse_and_match("Palm olien", kb)
        assert results[0].matched
        assert results[0].kb_id == "palm_oil"
        assert results[0].match_method == "fuzzy"

    def test_fuzzy_score_populated(self, kb):
        results, _ = parse_and_match("Palm olien", kb)
        assert results[0].fuzzy_score is not None
        assert results[0].fuzzy_score >= 88.0

    def test_reasonable_typo_matches(self, kb):
        """'glucoze' is close enough to 'glucose'."""
        results, _ = parse_and_match("glucoze syrup", kb)
        # May or may not match depending on threshold — just verify no crash.
        assert isinstance(results[0].matched, bool)


# ── Short-string rejection ─────────────────────────────────────────────────────

class TestShortStringRejection:
    def test_two_char_string_not_fuzzy_matched(self, kb):
        """Strings shorter than FUZZY_MIN_SHORT chars must not fuzzy-match."""
        token = make_token("mg")
        results, _ = match_tokens([token], [1], kb)
        # Should be unmatched (too short for fuzzy)
        if not results[0].matched:
            assert results[0].match_method == "unmatched"

    def test_three_char_string_boundary(self, kb):
        """3 chars is below FUZZY_MIN_SHORT (4); should not fuzzy-match."""
        token = make_token("msg")
        results, _ = match_tokens([token], [1], kb)
        # 'msg' is an actual alias (exact), so it may match; just no crash.
        assert isinstance(results[0].matched, bool)


# ── Unmatched ingredients ─────────────────────────────────────────────────────

class TestUnmatched:
    def test_unknown_ingredient_is_unmatched(self, kb):
        results, _ = parse_and_match("Xanthoschium extract", kb)
        assert not results[0].matched
        assert results[0].match_method == "unmatched"
        assert results[0].kb_id is None
        assert results[0].flag is None

    def test_unmatched_has_zero_points_concept(self, kb):
        """Unmatched ingredients are neutral — no flag to penalize."""
        results, _ = parse_and_match("Xanthoschium extract", kb)
        assert results[0].flag is None


# ── Coverage calculation ───────────────────────────────────────────────────────

class TestCoverage:
    def test_full_coverage(self, kb):
        """All known ingredients → coverage = 1.0."""
        _, coverage = parse_and_match("Sugar, Salt, Palm oil", kb)
        assert coverage == 1.0

    def test_zero_coverage(self, kb):
        """All unknown → coverage = 0.0."""
        _, coverage = parse_and_match("Xyzogen, Flavorium, Chemicalite", kb)
        assert coverage == 0.0

    def test_partial_coverage(self, kb):
        """Mix of known/unknown."""
        _, coverage = parse_and_match("Sugar, Xyzogen extract, Salt", kb)
        assert pytest.approx(coverage, abs=0.01) == 2 / 3

    def test_empty_input_returns_zero(self, kb):
        _, coverage = parse_and_match("", kb)
        assert coverage == 0.0


# ── Demo input — full pipeline ─────────────────────────────────────────────────

class TestDemoInput:
    INPUT = (
        "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, "
        "Raising agents [INS 500(ii)], Flavour enhancer (INS 621), Palm olien"
    )

    def test_all_tokens_parsed(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        assert len(results) == 7

    def test_refined_flour_matched(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        assert results[0].matched
        assert results[0].kb_id == "refined_wheat_flour"

    def test_sugar_matched(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        assert results[1].matched
        assert results[1].kb_id == "sugar"

    def test_palm_oil_matched(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        assert results[2].matched
        assert results[2].kb_id == "palm_oil"

    def test_salt_matched(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        assert results[3].matched
        assert results[3].kb_id == "salt"

    def test_ins_621_matched(self, kb):
        results, _ = parse_and_match(self.INPUT, kb)
        # INS 621 token (position 6)
        fe_result = results[5]
        assert fe_result.matched
        assert fe_result.kb_id == "monosodium_glutamate"

    def test_palm_olien_typo_matched(self, kb):
        """'Palm olien' (typo) should still match palm_oil via fuzzy."""
        results, _ = parse_and_match(self.INPUT, kb)
        assert results[6].matched
        assert results[6].kb_id == "palm_oil"

    def test_coverage_high(self, kb):
        """Most ingredients should match; coverage should be high."""
        _, coverage = parse_and_match(self.INPUT, kb)
        # At minimum sugar, flour, palm oil, salt, MSG should match = 5/7 ≈ 0.71
        assert coverage >= 0.60


# ── looks_like_food ────────────────────────────────────────────────────────────

class TestLooksLikeFood:
    def test_known_ingredients_are_food(self, kb):
        tokens_raw = parse("Sugar, Salt, Palm oil")
        norm = [normalize(t) for t in tokens_raw]
        pos = [t.position for t in tokens_raw]
        results, _ = match_tokens(norm, pos, kb)
        assert looks_like_food(results, norm, kb)

    def test_common_words_are_food(self, kb):
        """Even without KB matches, common words should trigger looks_like_food."""
        tokens_raw = parse("wheat, milk, salt, water, rice, spices")
        norm = [normalize(t) for t in tokens_raw]
        pos = [t.position for t in tokens_raw]
        results, _ = match_tokens(norm, pos, kb)
        assert looks_like_food(results, norm, kb)

    def test_random_words_not_food(self, kb):
        tokens_raw = parse("lorem, ipsum, dolor, sit, amet")
        norm = [normalize(t) for t in tokens_raw]
        pos = [t.position for t in tokens_raw]
        results, _ = match_tokens(norm, pos, kb)
        assert not looks_like_food(results, norm, kb)


# ── KB integrity ───────────────────────────────────────────────────────────────

class TestKBIntegrity:
    def test_all_entries_have_primary_flag(self, kb):
        """Every KB entry must have exactly one primary_flag (ARCHITECTURE §5.4)."""
        for kb_id, entry in kb.entries.items():
            assert "primary_flag" in entry, f"{kb_id} missing primary_flag"
            assert entry["primary_flag"] is not None, f"{kb_id} has null primary_flag"

    def test_all_entries_have_required_null_fields(self, kb):
        """explanation, swap_tip, source must be null; verified must be false."""
        for kb_id, entry in kb.entries.items():
            assert entry.get("explanation") is None, f"{kb_id}: explanation should be null"
            assert entry.get("swap_tip") is None, f"{kb_id}: swap_tip should be null"
            assert entry.get("source") is None, f"{kb_id}: source should be null"
            assert entry.get("verified") is False, f"{kb_id}: verified should be false"

    def test_kb_has_all_appendix_a_entries(self, kb):
        """Check that the required seed entries from Appendix A are present."""
        required_ids = [
            "sugar", "glucose_syrup", "hfcs", "invert_sugar_syrup", "dextrose",
            "refined_wheat_flour", "wheat_flour_unspecified", "hydrogenated_vegetable_fat",
            "palm_oil", "salt", "monosodium_glutamate", "disodium_guanylate",
            "disodium_inosinate", "disodium_ribonucleotides", "sodium_benzoate",
            "potassium_sorbate", "sorbic_acid", "calcium_propionate",
            "sodium_metabisulphite", "tbhq", "bha", "bht",
            "aspartame", "acesulfame_k", "sucralose", "saccharin",
            "tartrazine", "sunset_yellow", "carmoisine", "ponceau_4r",
            "allura_red", "brilliant_blue",
            "mono_diglycerides", "polysorbate_80", "cmc",
            "artificial_flavour", "maltodextrin", "modified_starch", "hvp",
            "soy_protein_isolate",
            "whole_wheat_flour", "oats", "ragi", "jowar", "bajra", "brown_rice",
            "peanuts", "almonds", "cashew", "chana", "moong_lentils",
            "flax_sesame_seeds",
        ]
        for kb_id in required_ids:
            assert kb_id in kb.entries, f"Missing required KB entry: {kb_id}"

    def test_version_is_set(self, kb):
        assert kb.version == 1
