"""
eval_golden.py - Evaluate the scoring engine against the golden product set.

Usage:
    cd backend
    python scripts/eval_golden.py

Targets (ARCHITECTURE §12 / PRD §3 S3):
  - ML-vs-rule band agreement >= 75%
  - ML path used on >= 70% of products
  - No crashes

The golden set (backend/app/data/golden/golden_products.json) is filled
by the owner with real product ingredient texts copied from packs.
The agent must NOT invent ingredient lists for real brands (PRD §15 rule 3).
"""
# M7 will implement the full evaluation loop.
# Stub: prints a reminder if the golden set is empty.

from __future__ import annotations

import json
import sys
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent.parent / "app" / "data" / "golden" / "golden_products.json"


def main() -> None:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        products = json.load(f)

    if not products:
        print(
            "Golden set is empty. The owner must copy ingredient texts from real packs "
            "into backend/app/data/golden/golden_products.json (see ARCHITECTURE Appendix B)."
        )
        sys.exit(0)

    print(f"Found {len(products)} golden products. Full evaluation will be implemented in M7.")


if __name__ == "__main__":
    main()
