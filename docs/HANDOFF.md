# NutriSnap Handoff

## Status
- M3a gate, orchestrator, API schema, mock-model fallbacks: complete (118 tests pass).
- ML is intentionally out of scope for this presentation. Production model remains `StubNovaModel`; health reports `disabled` and normal analysis returns `rule_based` / `ml_disabled`.
- `hf_nova.py` and `minilm_head.py` stay stubs. `NOVA_BACKEND` remains the future adapter selector.
- M3b/SQLite phase: complete. Schema/seeding, best-effort scan writes, history/stats/query endpoints, 12 query examples, docs, and tests are in place.
- Current work: frontend, Windows run/evaluation polish.

## Project layout
- Backend: `backend/app/core/` parser, normalizer, matcher, rules, gate, scoring, and ML protocol/stubs.
- API: `backend/app/api/routes.py`; schemas: `backend/app/schemas.py`.
- Seed KB: `backend/app/data/kb/ingredients.json`, `category_rules.json`, `category_notes.json`.
- Tests: `backend/tests/`; golden set: `backend/app/data/golden/golden_products.json`.
- SQLite: `backend/app/core/database.py`; initialize with `cd backend; .venv\Scripts\python.exe scripts\init_db.py`.
- Frontend currently scaffold pending.

## Run and verify
- Backend tests: from `backend`, `.venv\Scripts\python.exe -m pytest -q tests`.
- Current result: 121 tests passed; `-p no:cacheprovider` avoids restricted pytest cache writes.
- Start API from `backend`: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`.
- Frontend setup/run: from `frontend`, `npm install` then `npm run dev`.
- No real model download or loading is allowed for this demo.

## Decisions and limits
- Use stdlib `sqlite3`, no ORM; persist scan scores and ingredient rows only, never submitted text or user identifiers.
- Do not fabricate branded ingredient lists or health claims. Empty golden data stays empty.
- ML plug-in remains available by selecting `NOVA_BACKEND` and implementing its adapter contract, but is disabled for this delivery.
- Known limitation: validated mock gate tests exercise future ML paths; the presentation runtime is rules-only.
