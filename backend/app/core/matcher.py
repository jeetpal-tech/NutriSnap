"""
matcher.py - Match normalized tokens against the knowledge base.

Spec: ARCHITECTURE.md §5.3, §5.3a

Match order:
  1. Exact: normalized name or any extracted INS code equals a KB alias/code.
  2. Fuzzy: rapidfuzz WRatio, score_cutoff=88.
             Reject if the shorter of (query, candidate) has < 4 characters.
  3. Unmatched: matched=False, neutral (no flag, no penalty).

kb_coverage = matched_tokens / total_tokens.

Dedupe note (§5.3 bullet 5 / §6.3):
  The matcher returns ALL matches (including duplicates for bilingual labels).
  Deduplication — counting each kb_id once at its smallest position — is
  enforced by the rule engine (rules.py). The matcher does NOT filter here
  so that the rule engine has full positional information.

looks_like_food (§5.3a):
  True if at least one token matched the KB OR ≥ 30% of tokens appear in
  the common_ingredients vocab. Vocab contains generic food words only;
  no health claims.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, process as rf_process

from app.core.knowledge_base import KnowledgeBase
from app.core.normalizer import NormalizedToken

logger = logging.getLogger(__name__)

# Minimum rapidfuzz score for a fuzzy match to be accepted.
FUZZY_CUTOFF = 88

# Minimum character length of the shorter string in a fuzzy comparison.
FUZZY_MIN_SHORT = 4


@dataclass
class MatchResult:
    """
    Match outcome for one normalized token.

    Attributes
    ----------
    position    1-based position from the parser token.
    raw         Original raw text.
    name        Normalized name used for matching.
    matched     True when a KB entry was found.
    kb_id       Knowledge-base identifier, or None when unmatched.
    canonical   Canonical display name from the KB entry.
    flag        primary_flag from the KB entry, or None.
    entry       Full KB entry dict (for display fields), or None.
    match_method  'exact_alias', 'exact_ins', 'fuzzy', or 'unmatched'.
    fuzzy_score   Rapidfuzz score (0-100), or None for exact/unmatched.
    """

    position: int
    raw: str
    name: str
    matched: bool = False
    kb_id: str | None = None
    canonical: str | None = None
    flag: str | None = None
    entry: dict[str, Any] | None = None
    match_method: str = "unmatched"
    fuzzy_score: float | None = None


def match_tokens(
    tokens: list[NormalizedToken],
    positions: list[int],
    kb: KnowledgeBase,
) -> tuple[list[MatchResult], float]:
    """
    Match a list of NormalizedTokens against the knowledge base.

    Parameters
    ----------
    tokens      Normalized tokens from normalizer.normalize().
    positions   Parallel list of 1-based positions (from parser tokens).
    kb          Loaded KnowledgeBase instance.

    Returns
    -------
    (results, kb_coverage)
        results      One MatchResult per input token.
        kb_coverage  Fraction of tokens that matched (0.0–1.0).
    """
    if not tokens:
        return [], 0.0

    # Pre-build list of all alias strings for fuzzy search.
    all_aliases = kb.all_aliases()

    results: list[MatchResult] = []

    for token, position in zip(tokens, positions):
        result = _match_one(token, position, kb, all_aliases)
        results.append(result)

    matched_count = sum(1 for r in results if r.matched)
    kb_coverage = matched_count / len(results) if results else 0.0

    logger.debug(
        "Matched %d / %d tokens (coverage %.2f).",
        matched_count,
        len(results),
        kb_coverage,
    )

    return results, kb_coverage


def looks_like_food(results: list[MatchResult], tokens: list[NormalizedToken], kb: KnowledgeBase) -> bool:
    """
    §5.3a relevance check.
    True if:
      - at least one token matched the KB, OR
      - at least 30% of tokens appear in the common_ingredients vocab.
    """
    if any(r.matched for r in results):
        return True

    if not tokens:
        return False

    vocab_hits = sum(1 for t in tokens if t.name in kb.vocab)
    return (vocab_hits / len(tokens)) >= 0.30


# ── Internal ───────────────────────────────────────────────────────────────────


def _match_one(
    token: NormalizedToken,
    position: int,
    kb: KnowledgeBase,
    all_aliases: list[str],
) -> MatchResult:
    base = MatchResult(position=position, raw=token.raw, name=token.name)

    # ── 1. Exact alias match ──────────────────────────────────────────────
    kb_id = kb.kb_id_for_alias(token.name)
    if kb_id:
        return _fill_match(base, kb_id, kb, "exact_alias")

    # ── 2. Exact INS code match ───────────────────────────────────────────
    for code in token.codes:
        # codes are 'INS NNN'; strip prefix and look up numeric part.
        numeric = code.replace("INS", "").strip().lower()
        # Also try without spaces and with various forms.
        for key in [numeric, numeric.replace(" ", ""), code.lower()]:
            kb_id = kb.kb_id_for_ins(key)
            if kb_id:
                return _fill_match(base, kb_id, kb, "exact_ins")

    # ── 3. Fuzzy match ────────────────────────────────────────────────────
    if len(token.name) >= FUZZY_MIN_SHORT:
        hit = rf_process.extractOne(
            token.name,
            all_aliases,
            scorer=fuzz.WRatio,
            score_cutoff=FUZZY_CUTOFF,
        )
        if hit is not None:
            candidate_alias, score, _ = hit
            # Reject if the *shorter* of query / candidate is too short.
            if min(len(token.name), len(candidate_alias)) >= FUZZY_MIN_SHORT:
                kb_id = kb.kb_id_for_alias(candidate_alias)
                if kb_id:
                    result = _fill_match(base, kb_id, kb, "fuzzy")
                    result.fuzzy_score = score
                    return result

    # ── 4. Unmatched ──────────────────────────────────────────────────────
    base.match_method = "unmatched"
    return base


def _fill_match(
    base: MatchResult,
    kb_id: str,
    kb: KnowledgeBase,
    method: str,
) -> MatchResult:
    """Populate a MatchResult from a KB entry."""
    entry = kb.get_entry(kb_id)
    if entry is None:
        # kb_id in index but entry missing — treat as unmatched.
        base.match_method = "unmatched"
        return base

    base.matched = True
    base.kb_id = kb_id
    base.canonical = entry.get("canonical")
    base.flag = entry.get("primary_flag")
    base.entry = entry
    base.match_method = method
    return base
