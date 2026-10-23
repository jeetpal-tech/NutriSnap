# NutriSnap — Decisions Log

See also: `docs/ARCHITECTURE.md` §15 (architectural decisions ADR-1 to ADR-13).

---

## Spike result (Plan A — hsilvosa/nova-group-classifier)

*Owner: fill this section after running `backend/notebooks/nova_spike.ipynb` in Colab.*

- Revision             : f252e3546650954596ff7e5926aab4559c433909
- hidden_size          : `<from Step 2>`
- n_features_in_       : `<from Step 3>`
- Pooling chosen       : `<cls | mean | concat | N/A — Plan B>`
- Sanity set           : `<n_correct>` / 12 correct, median confidence `<median_conf>`
- Plan A accepted      : `<yes | no>`
- Indian subset        : n=`<n>`, accuracy=`<acc>`, macro-F1=`<f1>`, gate fallback=`<rate%>`
- Decision             : Use `<Plan A with <pooling> pooling | Plan B MiniLM head>`
- Calibration note     : `<over-confident? raise ML_MIN_CONFIDENCE?>`

---

## M0 — Scaffold (2026-10-21)

- `ml_status` is hardcoded to `"disabled"` in `GET /api/health` until M3.
- `extension/` folder is skipped per the session instructions (built in M11).
- `frontend/` directory created (empty; filled in M4a).
- `Wheat flour (unspecified)` entry added with `refined_flour` flag per Appendix A;
  `_owner_note` field marks it for owner confirmation before the demo.

---

## Open questions

1. **`wheat_flour_unspecified` flag**: Appendix A notes "owner to confirm; label wording
   is ambiguous". Current flag is `refined_flour`. Owner should verify and update before
   the demo.
2. **KB verification**: Owner should verify at least 30 seed entries against FSSAI,
   ICMR-NIN, WHO or peer-reviewed literature and set `verified: true` with a `source`.
   All entries are currently `verified: false` and `explanation: null` — unverified text
   will be hidden in the demo per `SHOW_UNVERIFIED_BADGE=true`.

---

## Known issues

- Presentation build is rules-only. Both selectable adapters remain stubs; no model is downloaded or loaded.
- The browser-based 360 px and 1280 px visual review could not be run in the current agent environment because no browser tool or Chrome/Edge executable is exposed.
- npm reported 13 dependency advisories (3 moderate, 10 high) during the frontend install; the app builds successfully. Revisit with `npm audit` before a public deployment.

## Presentation delivery (2026-10-22)

- Chose stdlib SQLite at `backend/data/nutrisnap.db`; pasted full ingredient text and user identifiers are never persisted.
- Kept `hf_nova.py` and `minilm_head.py` as non-loading stubs. `NOVA_BACKEND` selects the future adapter seam; runtime status remains disabled.
- The MiniLM integration expects local encoder files plus `head.joblib` and `label_map.json` in `backend/models/minilm-head/`; see README for the activation checklist.
- Golden evaluation uses only owner-supplied products and reports rules-only band agreement. The supplied golden JSON is empty.

## Repair pass (2026-10-22)

- Kept SQLite for the current single-node demo rather than introducing PostgreSQL or MongoDB. The schema now records scan lifecycle state, opaque public IDs, idempotency metadata, result snapshots, ingredient children, and provider-attempt outcomes.
- Removed the customer-facing database explorer and internal query/stat routes. Database diagrams and SQL examples remain documentation/local-tool material for the presentation.
- Gemini remains enrichment/OCR only. It is attempted before stored notes when configured; transient failures are retried within a bounded deadline, valid partial responses survive, and missing items stay unknown rather than becoming low risk.
- A live smoke request on 2026-10-22 returned HTTP 429/exhausted-quota behavior. The app completed with a limited fallback result and recorded the provider outcome. This is evidence of graceful degradation, not proof of healthy quota or provider availability.
- Fixed a migration edge case where an older `provider_attempt` table could retain a foreign key to a deleted `scan_legacy` table after the scan-table rebuild. `initialize()` repairs that table without discarding rows.
- Replaced the customer UI with the neo-brutalist design system and removed the public `/database` route. Exact 360 px and 1280 px screenshot review remains an owner check.
- Broader session ownership/production security work from the repair prompt was explicitly deferred by the owner; do not expand that scope in this pass.
