# NutriSnap Handoff

## Status
- Original delivery phases 1–4 are complete. The follow-on MiniLM, Gemini, camera scan, and demo UI phases A–F are implemented and committed.
- A: MiniLM head adapter loads numeric NPZ + JSON, normalizes encoder output, applies linear softmax head, and gates readiness on 12 startup examples.
- A runtime validation remains outstanding: NumPy installation timed out; CPU PyTorch and encoder download were not completed. The synthetic NPZ unit test skips without NumPy.
- B: Gemini JSON-schema OCR, ingredient information, and alternatives use a 20-second timeout, SQLite caches, and owner-KB overrides. Provider failures are contained. Tests mock Gemini; no provider calls are made by tests.
- C: `/api/scan-image` handles in-memory images up to 5 MB; text and image scans share scoring. Health reports ML and Gemini status.
- D: SQLite WAL/FK, source, redacted reopenable results, null reserved user_id, IST history, migrations, 16 SQL queries, and query-plan display are in place.
- E: Camera-first scan/capture/upload, 1280 px JPEG resize, paste mode, progress, editable OCR text, results and concern-sorted detail, searchable history, and database explorer are implemented.
- F: Golden eval, warm-cache script, Windows setup instructions, CPU PyTorch install, and root `run_dev.bat` are documented.

## Run
- One time, from project root: create `backend\.venv`, install CPU torch with `pip install torch --index-url https://download.pytorch.org/whl/cpu`, install `backend\requirements.txt`, run `npm --prefix frontend install`, and copy `backend\.env.example` to `backend\.env`.
- Add `GEMINI_API_KEY` to ignored `backend\.env` for image OCR and generated explanations. Do not commit credentials.
- Launch from project root with `run_dev.bat`; open `http://localhost:5173`. API docs: `http://localhost:8000/docs`.
- Local head files: `backend/models/minilm-head/head.npz`, `head_config.json`. Encoder files go in `backend/models/minilm-encoder/` and can download once on first startup.

## Verification and limits
- Backend: 129 passed, 1 skipped (NumPy unavailable), one Starlette/httpx deprecation warning.
- Frontend: `npm run build` succeeds. `eval_golden.py` succeeds with the intentionally empty golden set. `init_db.py` and `demo_queries.py` run successfully.
- Browser review at 360 px and 1280 px is outstanding; this environment has no browser tool or Chrome/Edge executable.
- MiniLM runtime and real Gemini calls remain unverified here. Supply a Gemini key and reachable network, and install CPU PyTorch/NumPy before presenting those integrations as live.
- npm previously reported 13 advisories (3 moderate, 10 high). Golden examples and health content require owner review; no branded ingredient lists were invented.
