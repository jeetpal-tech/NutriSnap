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

*(To be updated as milestones progress.)*
