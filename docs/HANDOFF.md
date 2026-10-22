# NutriSnap Handoff

## Status
- Original delivery phases 1–4 are complete; current request adds MiniLM, Gemini, image scan, and camera-first demo features.
- Phase A adapter implemented. `NOVA_BACKEND=minilm_head` loads the supplied numeric NPZ head and local/downloaded MiniLM encoder; startup self-test gates use.
- Phase A runtime validation is blocked: PyPI transfers repeatedly timed out while downloading NumPy (26 KB/s); CPU torch and encoder download were not reached. Synthetic head test is present but skipped without NumPy.
- Phase B complete: Gemini JSON-schema service for OCR text, ingredient summaries, and alternatives; SQLite cache, owner-KB override, 20-second timeout, no credential/prompt logging. Mock tests do not use the network.
- Phase C complete: `/api/scan-image` accepts in-memory multipart images up to 5 MB; OCR and paste share the scoring pipeline; responses add source, detected text, summaries, alternatives; health reports Gemini configuration.
- Phase D complete: scan source check, redacted result JSON, reserved null user_id, WAL/FK per connection, IST history, migrations, 16 queries plus EXPLAIN plan, SQLite rationale/normalization/privacy docs.
- Phases E–F remain in progress.

## Components
- Backend: `backend/app/core/` parser, matcher, rules, scoring, gate, SQLite layer, Gemini service, and model adapters.
- API: `backend/app/api/routes.py`; endpoints: analyze, health, history, stats, and queries.
- Database: `backend/data/nutrisnap.db` (ignored); schema, idempotent seeding, and best-effort scan writes in `backend/app/core/database.py`.
- Frontend: `frontend/src/App.jsx`; Scan, Results, History, and Database routes; Tailwind tokens in `frontend/tailwind.config.js`.
- Twelve demo SQL queries: `docs/QUERIES.sql`; database diagram: `docs/DATABASE.md`.

## Run
- Setup backend: `cd backend; py -3 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt`.
- Setup frontend once: `cd frontend; npm install`.
- Start both after setup: run root `run_dev.bat`.
- Run API alone from `backend`: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`.
- Run UI alone from `frontend`: `npm run dev`; configure API with `VITE_API_URL` in `.env`.

## Verification
- Latest backend: 129 passed, 1 skipped (NumPy unavailable), 1 warning.
- Frontend before current change: `npm run build` succeeds.
- `eval_golden.py` handles empty and populated owner-supplied JSON; current golden set is empty.
- `init_db.py` and `demo_queries.py` run from `backend`.
- Visual check at 360 px and 1280 px is pending because this environment exposes no browser tool or Chrome/Edge executable.

## Model files and activation
- Head files are local/ignored: `backend/models/minilm-head/head.npz` and `head_config.json`; encoder target: `backend/models/minilm-encoder/`.
- `.env.example` uses `NOVA_BACKEND=minilm_head`, `NOVA_MODEL_DIR=backend/models/minilm-head`, and `ML_ENABLED=true`.

## Known limitations
- Network package/model downloads are unavailable or too slow in this environment; verify the adapter on a connected machine.
- The 360/1280 visual browser review remains outstanding.
- npm reported 13 advisories (3 moderate, 10 high); recheck before any public deployment.
- Golden products and KB verification must be supplied/reviewed by the owner. Do not invent branded ingredient data or health claims.
