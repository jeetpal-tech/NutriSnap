"""
knowledge_base.py - Load and index ingredient entries and scoring tables.

Files loaded (ARCHITECTURE §5.4, §6.2, §14):
  app/data/kb/ingredients.json
  app/data/kb/category_rules.json
  app/data/kb/category_notes.json

The alias index maps every alias/INS code (lowercased) → kb_id.
This module is used by matcher.py and rules.py; it has no ML dependency.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve paths relative to this file so the server can be started from any cwd.
_DATA_DIR = Path(__file__).parent.parent / "data"
_INGREDIENTS_PATH = _DATA_DIR / "kb" / "ingredients.json"
_RULES_PATH = _DATA_DIR / "kb" / "category_rules.json"
_NOTES_PATH = _DATA_DIR / "kb" / "category_notes.json"
_VOCAB_PATH = _DATA_DIR / "vocab" / "common_ingredients.txt"


class KnowledgeBase:
    """
    Loaded once at startup; exposes:
      entries      dict[kb_id → entry_dict]
      rules        the full category_rules dict
      notes        list of category note dicts
      alias_index  dict[lowercased alias/ins_code → kb_id]
      ins_index    dict[ins_code_str → kb_id]   (e.g. "211" → "sodium_benzoate")
      version      int (from category_rules.json)
      vocab        set[str]  (common ingredient words for looks_like_food)
    """

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.rules: dict[str, Any] = {}
        self.notes: list[dict[str, Any]] = []
        self.alias_index: dict[str, str] = {}
        self.ins_index: dict[str, str] = {}
        self.version: int = 0
        self.vocab: set[str] = set()

    # ── Public ─────────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load all KB files and build indexes."""
        self._load_entries()
        self._load_rules()
        self._load_notes()
        self._load_vocab()
        self._build_indexes()

    def get_entry(self, kb_id: str) -> dict[str, Any] | None:
        return self.entries.get(kb_id)

    def all_aliases(self) -> list[str]:
        """Return every lowercased alias in the index (for fuzzy matching)."""
        return list(self.alias_index.keys())

    def kb_id_for_alias(self, alias: str) -> str | None:
        return self.alias_index.get(alias.lower())

    def kb_id_for_ins(self, code: str) -> str | None:
        """Look up a normalized INS code like '211' or '500ii'."""
        return self.ins_index.get(code.lower())

    # ── Private ────────────────────────────────────────────────────────────────

    def _load_entries(self) -> None:
        with open(_INGREDIENTS_PATH, encoding="utf-8") as f:
            raw: list[dict[str, Any]] = json.load(f)
        for entry in raw:
            kb_id = entry["id"]
            self.entries[kb_id] = entry
        logger.debug("Loaded %d KB entries.", len(self.entries))

    def _load_rules(self) -> None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            self.rules = json.load(f)
        self.version = self.rules.get("version", 0)

    def _load_notes(self) -> None:
        with open(_NOTES_PATH, encoding="utf-8") as f:
            self.notes = json.load(f)

    def _load_vocab(self) -> None:
        if _VOCAB_PATH.exists():
            with open(_VOCAB_PATH, encoding="utf-8") as f:
                for line in f:
                    word = line.strip().lower()
                    if word and not word.startswith("#"):
                        self.vocab.add(word)
        logger.debug("Loaded %d common ingredient words.", len(self.vocab))

    def _build_indexes(self) -> None:
        """
        Build alias_index and ins_index from loaded entries.
        For each entry:
          - canonical name (lowercased) → kb_id
          - each alias (lowercased) → kb_id
          - each INS code (string, lowercased) → kb_id
        """
        for kb_id, entry in self.entries.items():
            # Canonical
            canonical = entry.get("canonical", "")
            if canonical:
                self.alias_index[canonical.lower()] = kb_id

            # Aliases
            for alias in entry.get("aliases", []):
                self.alias_index[alias.lower()] = kb_id

            # INS codes stored as list of ints or strings
            for ins_raw in entry.get("ins", []):
                code = str(ins_raw).lower().strip()
                if code:
                    self.ins_index[code] = kb_id

        logger.debug(
            "Built alias index: %d entries, %d INS codes.",
            len(self.alias_index),
            len(self.ins_index),
        )
