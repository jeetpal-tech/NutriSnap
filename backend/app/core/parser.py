"""
parser.py - Raw ingredient text → ordered list of IngredientToken objects.

Spec: ARCHITECTURE.md §5.1
  - Split on ',' and ';' at bracket depth 0 only (track () and []).
  - Keep bracket content as sub_text.
  - Extract percentages: (59%), 59 %, 59.5%.
  - Strip leading words: 'contains', 'ingredients:', 'ingredients'.
  - Extract INS/E codes via regex; normalize to canonical form 'INS 211'.
  - Position = 1-based order on the label.
  - Cap at 80 tokens; log a warning when truncated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Maximum tokens per label (ARCHITECTURE §5.1).
MAX_TOKENS = 80

# Regex to detect and strip leading boilerplate prefixes (case-insensitive).
_PREFIX_RE = re.compile(
    r"^(?:ingredients?\s*(?:list)?\s*[:\-]?\s*|contains\s*[:\-]?\s*)",
    re.IGNORECASE,
)

# Percentage patterns: (59%), 59%, 59.5 %, (59.5%).
_PCT_RE = re.compile(r"\(?\s*(\d+(?:\.\d+)?)\s*%\s*\)?")

# INS / E code extractor.
# Matches: INS 211, INS-211, E211, E 211, INS 500(ii), INS500ii etc.
# Capture group 1 = the numeric+letter part (e.g. '211', '500(ii)', '500ii').
_INS_RE = re.compile(
    r"\b(?:INS|E)\s*-?\s*(\d{3,4}[a-z]?(?:\s*\(\w+\))?)",
    re.IGNORECASE,
)


@dataclass
class IngredientToken:
    """
    One parsed ingredient (or additive code) from the label.

    Attributes
    ----------
    position    1-based position on the label (descending weight order).
    raw         The original text slice for this token.
    name        Token text with bracket content and percentage stripped,
                ready for the normalizer.
    sub_text    Content inside the outermost bracket group, if present
                (e.g. 'INS 500(ii), INS 503(ii)' for 'Raising agents [...]').
    percent     Declared percentage, or None.
    ins_codes   INS codes extracted from this token (canonical form 'INS NNN').
    """

    position: int
    raw: str
    name: str
    sub_text: str | None = None
    percent: float | None = None
    ins_codes: list[str] = field(default_factory=list)


def parse(text: str) -> list[IngredientToken]:
    """
    Parse a raw ingredient string into a list of IngredientToken objects.

    Parameters
    ----------
    text : str
        The full ingredient list as pasted by the user (may include
        'Ingredients:', 'Contains:', nested brackets, percentages,
        INS/E codes, etc.)

    Returns
    -------
    list[IngredientToken]
        Ordered list of tokens, capped at MAX_TOKENS (80).
    """
    if not text:
        return []

    # 1. Strip leading boilerplate prefix.
    text = _PREFIX_RE.sub("", text.strip())

    # 2. Split at depth-0 commas and semicolons.
    raw_segments = _split_at_depth_zero(text)

    tokens: list[IngredientToken] = []

    for position, segment in enumerate(raw_segments, start=1):
        if position > MAX_TOKENS:
            logger.warning(
                "Ingredient list truncated at %d tokens (had %d segments).",
                MAX_TOKENS,
                len(raw_segments),
            )
            break

        segment = segment.strip()
        if not segment:
            continue

        token = _build_token(position, segment)
        tokens.append(token)

    return tokens


# ── Internal helpers ───────────────────────────────────────────────────────────


def _split_at_depth_zero(text: str) -> list[str]:
    """
    Split *text* on ',' and ';' that are at bracket depth 0.
    Both () and [] contribute to bracket depth.
    """
    segments: list[str] = []
    depth = 0
    current: list[str] = []

    for ch in text:
        if ch in ("(", "["):
            depth += 1
            current.append(ch)
        elif ch in (")", "]"):
            depth = max(0, depth - 1)  # Guard against malformed input.
            current.append(ch)
        elif ch in (",", ";") and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)

    # Don't forget the last segment.
    if current:
        segments.append("".join(current))

    return segments


def _extract_sub_text(raw: str) -> tuple[str, str | None]:
    """
    Find the outermost bracket group in *raw* and return
    (text_without_bracket, bracket_content).

    Only strips the first outermost group; a percentage-only group
    like '(61%)' is NOT treated as sub_text — the caller handles that.
    """
    # Find the first opening bracket.
    for open_ch, close_ch in (("[", "]"), ("(", ")")):
        start = raw.find(open_ch)
        if start == -1:
            continue

        # Find the matching close at the same depth.
        depth = 0
        for i, ch in enumerate(raw[start:], start=start):
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    inner = raw[start + 1 : i].strip()
                    # Skip pure-percentage groups like '(61%)'.
                    if _PCT_RE.fullmatch(inner.strip("() ")):
                        break
                    outer = (raw[:start] + raw[i + 1 :]).strip()
                    return outer, inner if inner else None

    return raw, None


def _extract_percent(raw: str) -> float | None:
    """Return the first percentage value found in *raw*, or None."""
    m = _PCT_RE.search(raw)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _normalize_ins_code(raw_code: str) -> str:
    """
    Normalize an extracted INS/E code to canonical form 'INS NNN'.
    Examples: '500(ii)' → 'INS 500(ii)', '211' → 'INS 211'.
    Strips surrounding whitespace and normalises inner spaces.
    """
    code = raw_code.strip()
    # Collapse spaces inside, e.g. '500 (ii)' → '500(ii)'.
    code = re.sub(r"\s+", "", code)
    # Lowercase the sub-letter suffix for consistency.
    return f"INS {code}"


def _extract_ins_codes(text: str) -> list[str]:
    """
    Extract all INS/E codes from *text* and return canonical forms.
    """
    codes: list[str] = []
    for m in _INS_RE.finditer(text):
        codes.append(_normalize_ins_code(m.group(1)))
    return codes


def _strip_ins_and_pct(text: str) -> str:
    """
    Remove percentage patterns and INS/E code patterns from text so the
    remaining string is a clean ingredient name.
    """
    # Remove percentages.
    text = _PCT_RE.sub("", text)
    # Remove INS/E references (the full token including 'INS '/'E ').
    text = re.sub(
        r"\b(?:INS|E)\s*-?\s*\d{3,4}[a-z]?(?:\s*\(\w+\))?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove stray bracket pairs left after code removal.
    text = re.sub(r"\[\s*\]|\(\s*\)", "", text)
    # Collapse whitespace and strip punctuation at the edges.
    text = re.sub(r"\s+", " ", text).strip(" ,;[]():")
    return text


def _build_token(position: int, raw: str) -> IngredientToken:
    """
    Build a single IngredientToken from a raw segment string.
    """
    # 1. Extract INS/E codes from the full raw text first.
    ins_codes = _extract_ins_codes(raw)

    # 2. Extract percentage.
    percent = _extract_percent(raw)

    # 3. Extract sub_text (bracket content that is NOT a percentage).
    text_without_bracket, sub_text = _extract_sub_text(raw)

    # 4. Build the clean name: strip INS codes and percentages from
    #    the part that remains outside the bracket group.
    name = _strip_ins_and_pct(text_without_bracket)

    # 5. If after stripping we have nothing (e.g. the token was purely
    #    'INS 500(ii)'), fall back to a minimal representation.
    if not name and ins_codes:
        name = ins_codes[0]
    elif not name:
        name = raw.strip()

    return IngredientToken(
        position=position,
        raw=raw,
        name=name,
        sub_text=sub_text,
        percent=percent,
        ins_codes=ins_codes,
    )
