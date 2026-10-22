# NutriSnap Handoff

## Status
- Delivery phases 1–4 implemented. M3a gate/orchestrator remains testable with mocks; model runtime is rules-only.
- `NOVA_BACKEND` selects a stub adapter. Both adapters report `disabled`; every normal successful analysis uses `rule_based` with `ml_disabled`.
- No ML weights are downloaded or loaded. `hf_nova.py` and `minilm_head.py` remain placeholders.

## Components
- Backend: `backend/app/core/` parser, matcher, rules, scoring, gate, SQLite layer, and adapter contract.
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
- Backend: 123 passed using `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests`.
- Frontend: `npm run build` succeeds.
- `eval_golden.py` handles empty and populated owner-supplied JSON; current golden set is empty.
- `init_db.py` and `demo_queries.py` run from `backend`.
- Visual check at 360 px and 1280 px is pending because this environment exposes no browser tool or Chrome/Edge executable.

## ML plug-in checklist
- Implement `MiniLMHeadModel` in `backend/app/core/ml/minilm_head.py` using `NovaModel` from `base.py`; keep gate and orchestrator response/error behavior.
- Place local files under `backend/models/minilm-head/`: `config.json`, `model.safetensors`, `tokenizer.json`, `tokenizer_config.json`, `special_tokens_map.json`, `vocab.txt`, `head.joblib`, `label_map.json`.
- Add pinned ML runtime dependencies, set `NOVA_BACKEND=minilm_head`, `NOVA_MODEL_DIR=backend/models/minilm-head`, and `ML_ENABLED=true`; restart and verify health, fallback tests, and owner-supplied evaluation before use. Default remains `ML_ENABLED=false`.

## Known limitations
- The 360/1280 visual browser review remains outstanding.
- npm reported 13 advisories (3 moderate, 10 high); recheck before any public deployment.
- Golden products and KB verification must be supplied/reviewed by the owner. Do not invent branded ingredient data or health claims.
