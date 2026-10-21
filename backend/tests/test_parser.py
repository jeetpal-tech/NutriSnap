"""
test_parser.py - Parser unit tests (ARCHITECTURE §12 parser cases).

All cases are deterministic; no ML model or network required.
"""
from __future__ import annotations

import pytest
from app.core.parser import MAX_TOKENS, parse


# ── Helpers ────────────────────────────────────────────────────────────────────

def names(tokens) -> list[str]:
    return [t.name.lower() for t in tokens]

def positions(tokens) -> list[int]:
    return [t.position for t in tokens]

def ins_codes_flat(tokens) -> list[str]:
    return [code for t in tokens for code in t.ins_codes]


# ── Basic splitting ────────────────────────────────────────────────────────────

class TestBasicSplitting:
    def test_simple_comma_list(self):
        tokens = parse("Sugar, Palm oil, Salt")
        assert names(tokens) == ["sugar", "palm oil", "salt"]

    def test_semicolon_separator(self):
        tokens = parse("Sugar; Palm oil; Salt")
        assert names(tokens) == ["sugar", "palm oil", "salt"]

    def test_mixed_separators(self):
        tokens = parse("Sugar, Palm oil; Salt")
        assert len(tokens) == 3

    def test_positions_are_one_based(self):
        tokens = parse("Sugar, Palm oil, Salt")
        assert positions(tokens) == [1, 2, 3]

    def test_empty_string_returns_empty(self):
        assert parse("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse("   ") == []


# ── Prefix stripping ───────────────────────────────────────────────────────────

class TestPrefixStripping:
    def test_ingredients_colon_prefix(self):
        tokens = parse("Ingredients: Sugar, Salt")
        assert names(tokens) == ["sugar", "salt"]

    def test_ingredients_no_colon(self):
        tokens = parse("Ingredients Sugar, Salt")
        assert names(tokens) == ["sugar", "salt"]

    def test_contains_colon_prefix(self):
        tokens = parse("Contains: Sugar, Salt")
        assert names(tokens) == ["sugar", "salt"]

    def test_contains_no_colon(self):
        tokens = parse("Contains Sugar, Salt")
        assert names(tokens) == ["sugar", "salt"]

    def test_ingredients_list_prefix(self):
        tokens = parse("Ingredient list: Wheat flour, Sugar")
        assert names(tokens) == ["wheat flour", "sugar"]

    def test_case_insensitive_prefix(self):
        tokens = parse("INGREDIENTS: Sugar, Salt")
        assert names(tokens) == ["sugar", "salt"]


# ── Percentages ───────────────────────────────────────────────────────────────

class TestPercentages:
    def test_percentage_in_parens(self):
        tokens = parse("Refined wheat flour (maida) (61%), Sugar, Palm oil")
        assert tokens[0].percent == 61.0

    def test_percentage_decimal(self):
        tokens = parse("Sugar (59.5%), Salt")
        assert tokens[0].percent == 59.5

    def test_percentage_with_space(self):
        tokens = parse("Sugar 59 %, Salt")
        assert tokens[0].percent == 59.0

    def test_name_excludes_percentage(self):
        tokens = parse("Refined wheat flour (61%)")
        assert "61" not in tokens[0].name
        assert "%" not in tokens[0].name

    def test_no_percentage(self):
        tokens = parse("Sugar, Salt")
        assert tokens[0].percent is None
        assert tokens[1].percent is None


# ── Nested brackets ───────────────────────────────────────────────────────────

class TestNestedBrackets:
    def test_raising_agents_nested_bracket(self):
        """
        'Raising agents [INS 500(ii), INS 503(ii)]' must be ONE token,
        not split at the comma inside the brackets.
        """
        tokens = parse(
            "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, "
            "Raising agents [INS 500(ii), INS 503(ii)], Flavour enhancer (INS 621)"
        )
        # Should be 6 tokens, not split inside brackets
        assert len(tokens) == 6
        # The raising agents token should contain INS codes
        raising = tokens[4]
        assert "INS 500" in " ".join(raising.ins_codes) or "500" in " ".join(raising.ins_codes)

    def test_sub_text_captured(self):
        """Bracket content is captured as sub_text."""
        tokens = parse("Raising agents [INS 500(ii), INS 503(ii)]")
        # sub_text should contain the bracket content
        assert tokens[0].sub_text is not None
        assert "500" in tokens[0].sub_text or "INS" in tokens[0].sub_text

    def test_double_nested_parens(self):
        """Deep nesting should not cause an index error."""
        tokens = parse("Sugar, Emulsifier (INS 471 (E471))")
        assert len(tokens) == 2

    def test_malformed_brackets_do_not_crash(self):
        """Unbalanced brackets should not crash the parser."""
        tokens = parse("Sugar, Palm oil [unrefined, Salt")
        assert len(tokens) >= 1


# ── INS / E code extraction ───────────────────────────────────────────────────

class TestINSCodes:
    def test_ins_code_normalized(self):
        """INS 211 should become 'INS 211' in ins_codes."""
        tokens = parse("Sodium benzoate (INS 211)")
        assert "INS 211" in tokens[0].ins_codes

    def test_e_code_normalized_to_ins(self):
        """E211 should normalize to 'INS 211'."""
        tokens = parse("Sodium benzoate (E211)")
        assert "INS 211" in tokens[0].ins_codes

    def test_ins_with_dash(self):
        """INS-211 variant."""
        tokens = parse("Preservative (INS-211)")
        assert "INS 211" in tokens[0].ins_codes

    def test_ins_500ii(self):
        """INS 500(ii) should be captured."""
        tokens = parse("Raising agent [INS 500(ii)]")
        codes = tokens[0].ins_codes
        assert any("500" in c for c in codes)

    def test_multiple_ins_codes_in_one_token(self):
        """Two INS codes in a bracket sub_text."""
        tokens = parse("Raising agents [INS 500(ii), INS 503(ii)]")
        all_codes = tokens[0].ins_codes
        assert any("500" in c for c in all_codes)
        assert any("503" in c for c in all_codes)

    def test_e_code_4digits(self):
        """E1422 (modified starch) should parse."""
        tokens = parse("Modified starch (E1422)")
        codes = tokens[0].ins_codes
        assert any("1422" in c for c in codes)


# ── 80-token cap ──────────────────────────────────────────────────────────────

class TestTokenCap:
    def test_long_list_truncated_to_80(self):
        """A list of 100 ingredients should be capped at 80 tokens."""
        long_list = ", ".join(f"ingredient{i}" for i in range(100))
        tokens = parse(long_list)
        assert len(tokens) == MAX_TOKENS

    def test_exactly_80_tokens_not_truncated(self):
        """Exactly 80 tokens should not trigger the warning / cap."""
        exact_list = ", ".join(f"ingredient{i}" for i in range(80))
        tokens = parse(exact_list)
        assert len(tokens) == 80


# ── Demo input ────────────────────────────────────────────────────────────────

class TestDemoInput:
    """
    The exact input from the milestone demo requirement.
    Input: "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt,
            Raising agents [INS 500(ii)], Flavour enhancer (INS 621), Palm olien"
    """
    INPUT = (
        "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, "
        "Raising agents [INS 500(ii)], Flavour enhancer (INS 621), Palm olien"
    )

    def test_token_count(self):
        tokens = parse(self.INPUT)
        assert len(tokens) == 7

    def test_first_token_is_flour(self):
        tokens = parse(self.INPUT)
        assert "wheat flour" in tokens[0].name or "maida" in tokens[0].sub_text or "flour" in tokens[0].name

    def test_first_token_percent(self):
        tokens = parse(self.INPUT)
        assert tokens[0].percent == 61.0

    def test_sugar_is_second(self):
        tokens = parse(self.INPUT)
        assert tokens[1].name.lower() == "sugar"

    def test_raising_agents_ins_code(self):
        tokens = parse(self.INPUT)
        raising = tokens[4]
        codes = raising.ins_codes
        assert any("500" in c for c in codes)

    def test_flavour_enhancer_ins_621(self):
        tokens = parse(self.INPUT)
        fe = tokens[5]
        codes = fe.ins_codes
        assert any("621" in c for c in codes)

    def test_palm_olien_last(self):
        tokens = parse(self.INPUT)
        assert "palm" in tokens[6].name or "olien" in tokens[6].name
