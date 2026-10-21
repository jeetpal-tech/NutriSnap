"""
normalizer.py - Clean an IngredientToken name for KB lookup.

Spec: ARCHITECTURE.md §5.2
  - Lowercase.
  - Remove percentages and trailing punctuation.
  - Collapse spaces.
  - Map unicode dashes/quotes to ASCII equivalents.
  - Strip diacritics (NFD decompose → remove combining chars).
  - Output: clean `name` (str) plus `codes` (list of canonical INS strings).

The normalizer works on the already-parsed IngredientToken; it does NOT
re-parse the raw text.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.core.parser import IngredientToken

# Unicode → ASCII replacements applied before lowercasing.
_UNICODE_MAP = str.maketrans(
    {
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u00b7": " ",  # middle dot (sometimes used as separator)
        "\u2019": "'",  # right single quotation mark (duplicate for safety)
    }
)

# Pattern to strip quantity/percentage remnants that the parser might leave.
_PCT_REMNANT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")

# Trailing/leading punctuation to strip after everything else.
_EDGE_PUNCT_RE = re.compile(r"^[\s,;:\-.()\[\]]+|[\s,;:\-.()\[\]]+$")


@dataclass
class NormalizedToken:
    """
    Result of normalizing one IngredientToken.

    Attributes
    ----------
    name    Clean, lowercase, diacritic-stripped ingredient name ready for
            alias lookup and fuzzy matching.
    codes   Canonical INS codes from the original token (e.g. ['INS 211']).
    raw     Original raw text (pass-through for display).
    """

    name: str
    codes: list[str]
    raw: str


def normalize(token: IngredientToken) -> NormalizedToken:
    """
    Normalize a parsed IngredientToken into a NormalizedToken.

    The `codes` field is taken directly from the token's `ins_codes`
    (already canonical from the parser).
    """
    name = _normalize_name(token.name)
    return NormalizedToken(name=name, codes=list(token.ins_codes), raw=token.raw)


def normalize_text(text: str) -> str:
    """
    Convenience function: normalize a plain string (not a token).
    Used internally by the matcher for alias comparison.
    """
    return _normalize_name(text)


# ── Internal ───────────────────────────────────────────────────────────────────


def _normalize_name(name: str) -> str:
    """
    Apply all normalization steps to a name string:
    1. Replace Unicode punctuation with ASCII equivalents.
    2. Lowercase.
    3. Strip percentage remnants.
    4. NFD decompose and remove combining (diacritic) characters.
    5. Collapse internal whitespace.
    6. Strip leading/trailing punctuation.
    """
    # 1. Unicode → ASCII punctuation map.
    name = name.translate(_UNICODE_MAP)

    # 2. Lowercase.
    name = name.lower()

    # 3. Remove percentage patterns that slipped through.
    name = _PCT_REMNANT_RE.sub("", name)

    # 4. Strip diacritics: decompose to NFD, remove combining marks.
    name = unicodedata.normalize("NFD", name)
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Mn")

    # 5. Collapse internal whitespace.
    name = re.sub(r"\s+", " ", name)

    # 6. Strip leading/trailing noise.
    name = _EDGE_PUNCT_RE.sub("", name)

    return name
