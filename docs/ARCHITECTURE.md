# NutriSnap - Architecture

Version 1.1 - 2026-10-20 - Deadline 2026-10-23 (v1.1 adds the NOVA badge, Nutri-Score grade, daily tracker, Hindi support, PDF export and a browser extension; see section 16). Companion to `docs/PRD.md`. **This file is the single source of truth for formulas, constants, API shapes and folder layout.** If another document disagrees, this one wins.

---

## 1. Constraints that shape every decision

| Constraint | Consequence |
|---|---|
| 3 days to a working demo (2026-10-23) | Release 1 = core scoring + NOVA badge + PDF export. The other extras are built behind feature flags and shown in the demo only if they pass their acceptance tests (section 16, `docs/PRD.md` section 10) |
| Hardware is not a constraint (owner confirmed) | CPU inference stays the default because it is simple and fast enough. Docker, Postgres or a larger model can be added later; nothing in Release 1 requires them |
| Demo may have no reliable internet | Model downloaded in advance and loaded from disk. No runtime calls to external APIs |
| Health domain | No invented health claims. Explanations must come from cited sources; unverified entries are flagged |
| Student team, first ML integration | Rules engine is complete and independent, so the app works even if ML integration fails entirely |

## 2. System context

```
Browser (React SPA, localStorage: history + profile)
   |  HTTP JSON  (VITE_API_URL, default http://localhost:8000)
   v
FastAPI (single process, single uvicorn worker)
   |-- Parser / Normalizer / Matcher  --> Knowledge Base (JSON files, loaded at startup)
   |-- Rule engine (always runs)
   |-- ML adapter (background-loaded) --> local model folder (backend/models/...)
   |-- Gate + Orchestrator  --> response
```

No database. The knowledge base and rule tables are versioned JSON files in the repo.

## 3. Components

| Component | File(s) | Responsibility |
|---|---|---|
| API layer | `app/main.py`, `app/api/routes.py`, `app/schemas.py` | Routing, validation (Pydantic v2), CORS, error shape |
| Parser | `app/core/parser.py` | Raw text to ordered list of ingredient tokens with position, percentage, INS/E codes |
| Normalizer | `app/core/normalizer.py` | Lowercase, strip punctuation/quantities, expand `INS`/`E` codes, collapse whitespace |
| Matcher | `app/core/matcher.py` | Exact alias lookup, then rapidfuzz fuzzy match against KB aliases |
| Knowledge base | `app/core/knowledge_base.py`, `app/data/kb/*.json` | Load and index ingredient entries and scoring tables |
| Rule engine | `app/core/rules.py` | Flag-based penalties/bonuses, rule base score, safety caps |
| Personalization | `app/core/personalization.py` | Profile multipliers applied to flag penalties |
| ML adapters | `app/core/ml/base.py`, `hf_nova.py`, `minilm_head.py` | Predict NOVA probabilities from ingredient text |
| Gate | `app/core/gate.py` | Decide ML vs fallback and produce reason codes |
| Orchestrator | `app/core/scoring.py` | End-to-end `analyze()`, builds the response |
| Frontend | `frontend/src/**` | Scan, Results, History pages, profile drawer; with flags: Tracker, language toggle, report/print views |
| NOVA badge | `app/core/nova_badge.py` | Derives the badge from the scoring result (16.1) |
| Nutri-Score | `app/core/nutriscore.py`, `app/data/nutriscore/*.json` | Nutrient-based A-E grade from the label's nutrition table (16.2) |
| Language | `app/core/language.py` | Script detection, Devanagari normalization, ML input selection (16.4) |
| Tracker | `frontend/src/lib/tracker.js`, `app/data/daily_targets.json` | Client-side daily totals vs limits (16.3) |
| Report | `frontend/src/report/*` | Print-optimized views for PDF export (16.5) |
| Extension | `extension/` | Chrome/Edge MV3 popup and context menu (16.6) |

## 4. Request lifecycle

```
POST /api/analyze {ingredients_text, profile?, force_mode?}
 1. validate (length 1..4000 chars)
 2. parse -> tokens
 3. if tokens < 2 or chars < 15            -> status "insufficient_input"
 4. normalize + match -> matches, kb_coverage
 5. if kb_coverage < 0.30 and not looks_like_food(text) -> status "not_food_text"
 6. rule = rules.score(matches, profile)      # always computed (cheap, deterministic)
 7. if force_mode == "rules" or ML disabled   -> return rule result (reason forced_rules / ml_disabled)
 8. try ml.predict(text, timeout) except -> return rule result (reason model_loading / model_error / model_timeout)
 9. reason = gate.check(pred, rule, kb_coverage)
10. if reason -> return rule result with fallback_reason
11. score = scoring.combine_ml(pred, matches, profile) ; apply safety caps
12. return ml_assisted result (includes rule_score for transparency)
```

**Where the extras plug in (section 16).** After step 1: `language.detect()` and normalization (16.4). After step 11/10: `nova_badge.build()` (16.1). Independently of scoring: if `nutrition` is present and `FEATURE_NUTRISCORE` is on, `nutriscore.compute()` (16.2). The tracker, PDF export and extension add no backend steps.

## 5. Backend modules (behavior spec)

### 5.1 Parser
- Split on `,` and `;` at bracket depth 0 only. Track depth for `()` and `[]`.
- Keep bracket content as `sub_text` (e.g. `Raising agents [INS 500(ii), INS 503(ii)]` yields parent token plus INS codes).
- Extract percentages `(59%)`, `59 %`, `59.5%` into `percent`.
- Strip leading words: `contains`, `ingredients:`, `ingredients`.
- Extract codes via regex `(?i)\b(?:INS|E)\s*-?\s*(\d{3,4}[a-z]?(?:\s*\(\w+\))?)` and normalize to canonical form `INS 211`.
- Position = 1-based order in the label (labels list ingredients in descending order by weight, so position approximates quantity).
- Cap at 80 tokens; truncate the rest with a warning.

### 5.2 Normalizer
Lowercase, remove percentages and trailing punctuation, collapse spaces, map unicode dashes/quotes, strip diacritics. Output a clean `name` plus `codes[]`.

### 5.3 Matcher
1. **Exact:** normalized name or any code equals a KB alias/INS code.
2. **Fuzzy:** `rapidfuzz.process.extractOne(name, aliases, scorer=fuzz.WRatio, score_cutoff=88)`. Reject matches where the shorter string has fewer than 4 characters.
3. **Unmatched:** `matched=false`, neutral (no penalty, no bonus). INS codes that are unmatched count as "unflagged additives" in rule base score.
4. `kb_coverage = matched_tokens / total_tokens`.
5. **Dedupe:** later rule scoring counts each `kb_id` once, at its smallest position (6.3).

### 5.3a looks_like_food (relevance check)
True if at least one token matches the KB **or** at least 30% of tokens appear in `app/data/vocab/common_ingredients.txt` (about 300 generic food words: wheat, milk, salt, water, rice, spices...). The vocab file contains words only, no health claims.

### 5.4 Knowledge base entry schema
```json
{
  "id": "palm_oil",
  "canonical": "Palm oil",
  "aliases": ["palmolein", "palm olein", "refined palm oil", "rbd palmolein"],
  "ins": [],
  "primary_flag": "saturated_fat_source",
  "category": "fat_oil",
  "explanation": null,
  "condition_notes": {"high_cholesterol": null},
  "swap_tip": null,
  "source": null,
  "verified": false
}
```
- Exactly **one** `primary_flag` per entry (prevents double counting).
- Release 2 adds optional fields `aliases_hi`, `aliases_hinglish`, `explanation_hi`, `swap_tip_hi`, `translation_verified` (section 16.4, Appendix D).
- Scoring uses only `primary_flag`, `aliases`, `ins`. Display text (`explanation`, `condition_notes`, `swap_tip`) is never used for scoring.
- `verified=true` requires a non-null `source` (`{"name": "...", "url": "..."}`) and a human-written explanation.
- The coding agent may add entries and aliases but must set `explanation`, `swap_tip`, `source` to `null` and `verified` to `false`. The owner fills and verifies them.
- Category-level notes with citations are in `app/data/kb/category_notes.json` (see Appendix A).

### 5.5 Flags

`added_sugar`, `refined_flour`, `trans_fat_source`, `saturated_fat_source`, `sodium_source`, `flavour_enhancer`, `preservative`, `artificial_sweetener`, `synthetic_colour`, `emulsifier_stabiliser`, `flavour_additive`, `ultra_processing_marker`, plus bonus flags `whole_grain_or_fibre`, `legume_nut_seed`.

## 6. Scoring specification

All constants live in `app/data/kb/category_rules.json` (loaded at startup, never hard-coded). Score is an integer 0-100, **higher is healthier**.

### 6.1 Bands
| Score | Band | UI colour token |
|---|---|---|
| 70-100 | Low Risk | `primary` (green) |
| 40-69 | Moderate Risk | `secondary` (amber) |
| 0-39 | High Risk | `tertiary` / `error` (red) |

### 6.2 `category_rules.json` (initial values; tune on the golden set)
```json
{
  "version": 1,
  "bands": {"high_risk_max": 39, "moderate_max": 69},
  "nova_base": {"1": 90, "2": 75, "3": 60, "4": 35},
  "rule_base": {
    "start": 85,
    "free_ingredient_count": 8, "per_extra_ingredient": 1, "complexity_max": 10,
    "per_unflagged_additive": 2, "unflagged_additive_max": 10
  },
  "flags": {
    "added_sugar":            {"penalty": 12, "position_weighted": true},
    "refined_flour":          {"penalty": 8,  "position_weighted": true},
    "saturated_fat_source":   {"penalty": 8,  "position_weighted": true},
    "trans_fat_source":       {"penalty": 20, "position_weighted": false},
    "sodium_source":          {"penalty": 3,  "position_weighted": false},
    "flavour_enhancer":       {"penalty": 6,  "position_weighted": false},
    "preservative":           {"penalty": 5,  "position_weighted": false},
    "artificial_sweetener":   {"penalty": 6,  "position_weighted": false},
    "synthetic_colour":       {"penalty": 5,  "position_weighted": false},
    "emulsifier_stabiliser":  {"penalty": 3,  "position_weighted": false},
    "flavour_additive":       {"penalty": 3,  "position_weighted": false},
    "ultra_processing_marker":{"penalty": 6,  "position_weighted": false}
  },
  "position_multiplier": {"1-3": 1.5, "4-6": 1.0, "7+": 0.7},
  "sugar_splitting_extra_penalty": 4,
  "penalty_cap": 70,
  "bonus": {"whole_grain_or_fibre": 4, "legume_nut_seed": 3, "cap": 10},
  "ml_penalty_scale": 0.6,
  "nova_markers": ["flavour_enhancer", "artificial_sweetener", "synthetic_colour", "emulsifier_stabiliser", "flavour_additive", "ultra_processing_marker", "trans_fat_source"],
  "profile_multipliers": {
    "diabetes":         {"added_sugar": 1.5, "refined_flour": 1.5, "ultra_processing_marker": 1.5},
    "hypertension":     {"sodium_source": 1.5, "flavour_enhancer": 1.5, "preservative": 1.5},
    "high_cholesterol": {"saturated_fat_source": 1.5, "trans_fat_source": 1.5}
  },
  "safety_caps": [
    {"if_flag_present": "trans_fat_source", "max_score": 69},
    {"if_flag_at_position_le": {"flag": "added_sugar", "position": 1}, "max_score": 69}
  ]
}
```

### 6.3 Rule-based score (fallback path)
```
base      = 85
            - min(10, max(0, n_tokens - 8) * 1)                  # complexity
            - min(10, 2 * n_unflagged_additives)                 # INS/E codes not covered by a flag
penalty   = sum over matched ingredients i with a penalty flag f:
              flags[f].penalty * pos_mult(position_i, f) * profile_mult(f)
            + sugar_splitting_extra_penalty   if >= 2 distinct added_sugar ingredients
penalty   = min(penalty, penalty_cap)
bonus     = min(bonus.cap, sum of bonus flags matched)
score_rule = clamp(round(base - penalty + bonus), 0, 100)
score_rule = apply_safety_caps(score_rule)
```
`pos_mult` applies only to flags with `position_weighted=true` (1-3: x1.5, 4-6: x1.0, 7+: x0.7). **Dedupe:** each `kb_id` is counted once per analysis, at its smallest position, so bilingual labels (every ingredient listed twice) and repeated sub-ingredients are not double-penalized. `profile_mult(f)` is the product of multipliers of all active profile conditions for flag `f` (default 1.0).

### 6.4 ML-assisted score
```
p        = [p1, p2, p3, p4]                       # NOVA class probabilities from the model
base_ml  = sum_k p[k] * nova_base[k]
score_ml = clamp(round(base_ml - ml_penalty_scale * penalty + bonus), 0, 100)
score_ml = apply_safety_caps(score_ml)
```
`penalty` and `bonus` are computed exactly as in 6.3 (so personalization works in both paths). The complexity and unflagged-additive terms are **not** applied in ML mode because NOVA already reflects processing.

Why `ml_penalty_scale = 0.6`: NOVA 4 already encodes the presence of sugar/additives, so applying full penalties would double count. Tune it so that rule and ML bands agree on at least 75% of the golden set.

### 6.5 Safety caps
Applied in both paths, after scoring. A cap can only lower a score. The response lists applied caps in `caps_applied`.

## 7. ML-assisted scoring and automatic fallback

### 7.1 Model choice

**Plan A (preferred): `hsilvosa/nova-group-classifier`** (Hugging Face, Apache-2.0)
- Predicts NOVA 1-4 from raw ingredient text. Reported on its model card (author's own split, not independently verified): top-1 accuracy 96.20%, weighted F1 0.9608, macro F1 0.8138; **NOVA 2 is weak** (precision 0.53, recall 0.33, F1 0.41).
- Trained on 30,000+ multilingual Open Food Facts records. About 0.1B parameters, `model.safetensors` about 541 MB.
- Repo files: `model.safetensors`, `config.json`, tokenizer files (`tokenizer.json`, `sentencepiece.bpe.model`, `vocab.txt`), and `nova_gb_model.joblib` (a scikit-learn `HistGradientBoostingClassifier` + `LabelEncoder`).
- **Integration gap:** the model card's example imports `src.models.nova_classifier.NOVAClassifier`, which is **not in the repo**, and the auto-generated `pipeline(...)` snippet will not produce NOVA labels. The apparent design is: transformer encoder embedding, then the joblib gradient-boosting head. Exact pooling and any extra features are undocumented and must be reverse-engineered (7.2).
- Low adoption (about 14 downloads/month at time of writing) and single author: treat as unverified until evaluated by us.
- Pin the revision: `f252e3546650954596ff7e5926aab4559c433909`.

**Plan B (fallback if the Plan A spike fails): own head on a small pretrained encoder**
- Encoder: `sentence-transformers/all-MiniLM-L6-v2` (about 22M params, about 90 MB, English, Apache-2.0). Frozen.
- Head: scikit-learn `LogisticRegression` (multinomial) or `HistGradientBoostingClassifier`, trained on Open Food Facts rows with `ingredients_text` and `nova_group`.
- Trained in Google Colab (free GPU), exported as `head.joblib` + `label_map.json`, loaded by `minilm_head.py`.
- This also satisfies "train the model a bit more": pretrained encoder plus a head we trained and evaluated.

Both adapters implement the same interface (7.4), so switching is `NOVA_BACKEND=minilm_head`.

### 7.2 Plan A integration spike (time-box: 2 hours, do first)

Run in Colab (free GPU, no local setup) or locally. Deliverable: `backend/notebooks/nova_spike.ipynb` plus a short result note in `docs/decisions.md`.

1. Download the pinned revision with `huggingface_hub.snapshot_download(repo_id, revision=...)`.
2. Read `config.json` (`model_type`, `hidden_size`) and the repo `README.md`.
3. `joblib.load("nova_gb_model.joblib")` (trusted pinned revision only). Print the object type, `classes_`, and `n_features_in_`.
4. Load `AutoTokenizer` and `AutoModel`. Compute embeddings with **CLS pooling** and **masked mean pooling**.
5. **Decision rule:** if `head.n_features_in_` equals `hidden_size` (or `2 * hidden_size` for CLS+mean concatenation), try those poolings. If it equals neither, **abandon Plan A** and start Plan B.
6. Sanity set (12 strings; expected NOVA in brackets, from the NOVA definitions on the model card): `"wheat"` [1], `"whole milk"` [1], `"sugar"` [2], `"refined palm oil"` [2], `"salt"` [2], a typical bread list [3], canned chickpeas, water, salt [3], and 5 clearly ultra-processed lists (instant noodles, cream biscuits, cola, packaged chips, flavoured yoghurt drink) [4].
7. Accept Plan A only if the chosen pooling gets at least 9 of 12 right **and** the probabilities are peaked (median top-1 probability >= 0.7).
8. Evaluate on Indian products (7.5). Record accuracy and macro-F1 in `docs/decisions.md`.

If any step fails, switch to Plan B immediately; do not spend more time debugging Plan A.

### 7.3 Gate (`app/core/gate.py`)

Inputs: model prediction `pred` (probabilities, top class, confidence, margin), `rule_score`, `ml_score`, `kb_coverage`. Output: `None` (use ML) or a reason code. Checks run in this order, first failure wins.

| # | Condition for fallback | Reason code | Default |
|---|---|---|---|
| 0 | `ML_ENABLED=false` | `ml_disabled` | |
| 1 | Model not loaded yet | `model_loading` | |
| 2 | Model failed to load or raised | `model_error` | |
| 3 | Inference exceeded timeout | `model_timeout` | 3.0 s |
| 3a | Fewer than 2 Latin-script tokens (for example Hindi-only text) and `ML_HINDI_SUPPORTED=false` | `unsupported_language` | |
| 4 | `confidence < ML_MIN_CONFIDENCE` | `low_confidence` | 0.60 |
| 5 | Top class is NOVA 2 and `confidence < ML_NOVA2_MIN_CONFIDENCE` | `weak_class_uncertain` | 0.80 |
| 6 | `top1 - top2 < ML_MIN_MARGIN` | `ambiguous_prediction` | 0.15 |
| 7 | `kb_coverage >= 0.60` and `ml_score - rule_score > ML_MAX_OPTIMISTIC_GAP` | `ml_rule_disagreement` | 25 |
| 8 | `kb_coverage >= 0.60` and `rule_score - ml_score > ML_MAX_PESSIMISTIC_GAP` | `ml_rule_disagreement` | 45 |
| - | `force_mode == "rules"` | `forced_rules` | |

Rationale for asymmetric thresholds (7 vs 8): for a health-warning tool, false reassurance is costlier than false caution, so ML is trusted less when it is more reassuring than the rules. Checks 7-8 are skipped when `kb_coverage < 0.60` because the rule score is unreliable (unknown ingredients are neutral, so it is optimistic).

Gate thresholds depend on calibrated probabilities. After the spike, check calibration on the Indian evaluation set (7.5) with a simple reliability table (10 bins). If the model is badly over-confident, raise `ML_MIN_CONFIDENCE`.

### 7.4 Adapter interface
```python
@dataclass
class NovaPrediction:
    probs: dict[int, float]      # {1: p1, 2: p2, 3: p3, 4: p4}, sums to ~1.0
    top: int
    confidence: float            # probs[top]
    margin: float                # top1 - top2
    latency_ms: int
    model_id: str

class NovaModel(Protocol):
    status: Literal["loading", "ready", "error", "disabled"]
    def load(self) -> None: ...                           # called in a background thread at startup
    def predict(self, text: str) -> NovaPrediction: ...   # raises ModelNotReady / ModelError
```
- Inference runs in a `ThreadPoolExecutor(max_workers=1)`; `future.result(timeout=ML_TIMEOUT_S)`; on timeout the caller falls back (the stray thread finishes in the background).
- Use `torch.inference_mode()`, `model.eval()`, `torch.set_num_threads(2)`, tokenizer `max_length=256, truncation=True`, batch size 1.
- Do not log full user text at INFO level.

### 7.5 Evaluation on Indian products (required before trusting ML)

Script: `backend/scripts/eval_nova_india.py` (runs in Colab or any machine with enough RAM; the dataset is large, so stream or query it remotely).

- Source: Hugging Face dataset `openfoodfacts/product-database` (parquet, `food` split, ODbL). It is large: **stream or query remotely, never download fully.** Suggested approach: DuckDB over `hf://datasets/openfoodfacts/product-database/food.parquet` with a filter on `countries_tags` containing `en:india`, `nova_group IS NOT NULL`, non-empty `ingredients_text`. **Verify the schema first:** `ingredients_text` may be a list of `{lang, text}` structs; select the English (or first Latin-script) text.
- Metrics: accuracy, macro-F1, per-class precision/recall, confusion matrix, and reliability table.
- Compare against a majority-class baseline so the numbers mean something.
- Report **fallback rate**: the share of Indian rows where the gate would reject ML (confidence gates only). If it is above 50%, the ML path will rarely run in the demo; loosen thresholds or switch to Plan B and retrain.
- Note: Open Food Facts assigns NOVA with its own rule-based algorithm from ingredients and additives, so high agreement shows the model reproduces that labelling, not that scores are medically correct. State this in the report.

### 7.6 Optional re-training ("train a bit more") - stretch goal S1

Only after P0 is done. In Colab: embed Indian-product ingredient texts with the same frozen encoder, train a new head (balanced class weights), compare to the original head on a held-out Indian split, and export `head_india.joblib`. Swap in via `NOVA_HEAD_PATH`. Do not full fine-tune the encoder (time and memory). Document before/after metrics.

## 8. Personalization

Active conditions come from `profile.conditions` (any of `diabetes`, `hypertension`, `high_cholesterol`). Multipliers are in `profile_multipliers` (6.2). The response lists `profile_effects`: for each affected flagged ingredient, the multiplier and the condition. UI shows "Personalized for X". Personalization never changes ML probabilities; it only changes the penalty term.

## 9. API contract

Base path `/api`. JSON. CORS limited to `CORS_ORIGINS`.

### 9.1 `GET /api/health`
```json
{"status": "ok", "ml_status": "ready", "ml_error": null, "gemini_status": "configured", "backend": "minilm_head", "kb_version": 1, "kb_entries": 42, "features": {"nutriscore": false, "hindi_ml": false}}
```
`ml_status` is `ready`, `loading`, `disabled`, `error`, or `error: selftest_failed`. `gemini_status` is `configured` or `missing_key`.

### 9.2 `POST /api/analyze`
Request:
```json
{
  "ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt, Raising agents [INS 500(ii)], Flavour enhancer (INS 621)",
  "profile": {"conditions": ["diabetes"]},
  "lang": "en",
  "nutrition": null,
  "force_mode": "auto"
}
```
`profile`, `lang`, `nutrition` and `force_mode` are optional. `lang` is `"en"` (default) or `"hi"`. `nutrition` is the per-100 g object defined in 16.2. `force_mode` is `"auto"` (default) or `"rules"`. Validation: `ingredients_text` 1-4000 chars, else HTTP 422 with `{"detail": [...]}`.

Response (HTTP 200):
```json
{
  "status": "ok",
  "score": 28,
  "band": "High Risk",
  "scoring_method": "ml_assisted",
  "fallback_reason": null,
  "rule_score": 33,
  "ml_score": 28,
  "nova": {"top": 4, "confidence": 0.93, "probs": {"1": 0.01, "2": 0.02, "3": 0.04, "4": 0.93}, "model_id": "hsilvosa/nova-group-classifier@f252e35", "latency_ms": 410},
  "kb_coverage": 0.83,
  "low_coverage_warning": false,
  "nova_badge": {"group": 4, "label": "Ultra-processed food", "source": "model", "confidence": 0.93, "basis": []},
  "nutriscore": {"status": "not_provided"},
  "language": {"detected": "latin", "ml_input": "full"},
  "flags": [
    {"flag": "added_sugar", "label": "Added sugar", "severity": "high"},
    {"flag": "saturated_fat_source", "label": "Saturated fat source", "severity": "medium"}
  ],
  "ingredients": [
    {
      "position": 1, "raw": "Refined wheat flour (maida) (61%)", "name": "refined wheat flour",
      "matched": true, "kb_id": "refined_wheat_flour", "canonical": "Refined wheat flour",
      "flag": "refined_flour", "risk": "medium", "points": -12.0,
      "explanation": null, "source": null, "verified": false
    }
  ],
  "profile_effects": [{"condition": "diabetes", "flag": "added_sugar", "multiplier": 1.5}],
  "caps_applied": [],
  "swap_tips": [{"flag": "saturated_fat_source", "tip": null}],
  "disclaimer": "Informational only, not medical advice. NOVA reflects processing level, not toxicity.",
  "attribution": "Contains information from Open Food Facts (ODbL).",
  "warnings": []
}
```
Rules for the shape:
- `scoring_method` is `"ml_assisted"` or `"rule_based"`. When `"rule_based"` after an ML attempt, `fallback_reason` is one of the codes in 7.3; when ML was never attempted because of the user/config, it is `forced_rules` / `ml_disabled`.
- `nova` is `null` when no prediction was made (or if it was made but rejected by the gate, include it so the UI can show "model said NOVA 3 at 41% confidence").
- `ml_score` is `null` if no prediction was made.
- `risk` per ingredient: `low | medium | high | neutral | unknown`. Unmatched ingredients are `unknown` with `points: 0`.
- `severity` of a flag: `high` if |points| >= 12, `medium` if >= 5, else `low`.
- `explanation`, `source`, `tip` may be null; UI must handle null (show nothing, never invent text).
- `nova_badge` is always present; `group` is null when `source` is `unavailable` (16.1).
- `nutriscore` is always present; `status` is `computed`, `missing_inputs`, `not_provided` or `disabled` (16.2).
- `language.ml_input` is `full` or `latin_only` (16.4). Explanations fall back to English with `explanation_lang: "en"` when no Hindi text exists.

Non-"ok" statuses (HTTP 200, no score):
```json
{"status": "insufficient_input", "message": "Please paste at least two ingredients.", "scoring_method": null}
{"status": "not_food_text", "message": "This does not look like an ingredient list.", "scoring_method": null}
```

### 9.3 Optional Gemini and image scan endpoints

- `POST /api/scan-image` accepts `multipart/form-data` with a `file` image field, maximum 5 MB. The backend reads and processes bytes in memory, never writes an image file, and never logs OCR text. Gemini copies the printed ingredients exactly; if OCR is unavailable, the response is `{ "status": "ocr_unavailable", "source": "camera", "message": "..." }` and the client can offer paste input. A successful response runs the same `/api/analyze` scorer and adds `source: "camera"`, `detected_text`, per-ingredient `ingredient_info`, and generic `alternatives`.
- `POST /api/analyze` adds `source: "paste"`, `ingredient_info`, and `alternatives` to the existing response. Gemini summaries are labeled `ai_generated: true`; owner-authored KB content takes precedence. Gemini output never changes score or flags.
- `GET /api/health` includes `gemini_status: "configured" | "missing_key"` and may expose `ml_status: "error: selftest_failed"` with `ml_error: "selftest_failed"` when the MiniLM smoke set fails.
- Gemini uses `GEMINI_MODEL` (default `gemini-3.5-flash`), a backend-only `GEMINI_API_KEY`, JSON-schema output, and a 20-second timeout. Provider errors degrade the optional feature and never produce HTTP 500.

### 9.4 Errors
HTTP 422 validation, HTTP 500 `{"detail": "internal_error"}` (never leak stack traces). An ML exception must **never** produce a 500; it becomes a rule-based response with `fallback_reason: "model_error"`.

## 10. Frontend architecture

React + Vite + Tailwind **3.4** (pinned, installed via npm, no CDN scripts). React Router.

### 10.1 Design brief (no external design export)

Goal: clean, trustworthy, readable at a glance. Verdict first, details second. The UI is built from this brief; there is no design file to import.

- **Theme:** light only (dark mode is out of scope). Page `#F7F8F6`, white cards, 1 px `line` borders, `rounded-2xl`, very soft shadow, 8 px spacing grid, content max width 1100 px, single column below 768 px.
- **Colour tokens** defined once in `tailwind.config.js`; components use token names only, never hard-coded hex values. Verify text contrast >= 4.5:1.

| Token | Value | Use |
|---|---|---|
| `page` / `surface` | `#F7F8F6` / `#FFFFFF` | Background / cards |
| `ink` / `muted` / `line` | `#1B1F1D` / `#5F6B66` / `#E2E6E3` | Text / secondary text / borders |
| `primary` / `primary-soft` | `#2E7D32` / `#E8F5E9` | Low Risk, main buttons |
| `warning` / `warning-soft` | `#995A00` / `#FFF4E0` | Moderate Risk |
| `danger` / `danger-soft` | `#C62828` / `#FDECEA` | High Risk |

- **Typography:** Inter for UI plus Noto Sans Devanagari (both via `@fontsource`). Scale 12/14/16/20/24/32 px, score numeral 48-56 px, weights 400/500/700.
- **Meaning is never colour alone:** the band always shows a text label (Low Risk / Moderate Risk / High Risk) and chips carry an icon plus text.
- **Components:** SVG score ring with numeral and band label; flag chips; ingredient rows as an accordion with a coloured left bar; icons from `lucide-react`; no stock photos, no emoji.
- **Motion:** ring fill about 600 ms, accordion about 150 ms, honour `prefers-reduced-motion`.
- **Content:** Indian examples (maida, vanaspati, palmolein, INS numbers); never placeholder health text.
- **Review loop:** after milestone M4a the owner reviews screenshots and may add reference images to `design/refs/`; the agent then matches that look. Restyling must be a token or component change, not a rewrite.

### 10.2 Screens
| Route | Component | Content | Notes |
|---|---|---|---|
| `/` | `ScanPage` | Title "Check your food ingredients"; textarea with Paste button; "Try an example" chips (generic ingredient lists, no brand names); disabled "Scan label photo" card marked "Coming soon"; Personalize card opening `ProfileDrawer`; "Analyze Ingredients" button; note "No account needed" | Reads `?ingredients=` and `autorun=1` (16.6) |
| `/results` | `ResultsPage` | Score ring, band, method badge with fallback explanation, NOVA badge card, flag chips, "Health impact factors" (top flags with points), ingredient accordion, low-coverage banner, disclaimer, "See Safer Alternatives" (swap-tip panel), "Save to Scan History", "Export PDF" | Core screen: spend design effort here |
| `/history` | `HistoryPage` | Search box, list rows with title, date, score pill, method, delete, clear all | |
| `/tracker` (flag) | `TrackerPage` | See 16.3 | Compose from the same tokens and components |
| `/report/:id`, `/report/tracker` (flag) | `ReportView` | Print layout, see 16.5 | |
| not built | product comparison | - | Out of scope this release; do not build, do not link |

### 10.3 Components
`AppShell` (top nav: Scan, History, Tracker (flag), Profile, language toggle (flag)), `ScoreRing` (SVG, colour by band, `role="img"` with aria-label), `FlagChip`, `IngredientAccordion`, `MethodBadge` ("AI-assisted" vs "Rule-based"), `FallbackNotice` (human text per reason code, section 10.5), `LowCoverageBanner`, `ProfileDrawer`, `SwapTipsPanel`, `Disclaimer`, `EmptyState`, `ErrorState`, `NovaBadge`, `NutritionForm`, `NutriScoreCard`, `TrackerPage`, `LogDialog`, `ReportView`, `LanguageToggle`.

### 10.4 State and storage
- `useAnalyze()` wraps `fetch` with 15 s timeout and error mapping.
- Results are passed by router state and mirrored in `sessionStorage` so refresh does not lose them.
- `localStorage` keys: `nutrisnap.history.v1` (max 50 items: `{id, createdAt, title, ingredientsText, result}`), `nutrisnap.profile.v1` (`{conditions: []}`), `nutrisnap.tracker.v1` (16.3), `nutrisnap.lang.v1` (`"en"` or `"hi"`).
- No accounts. No data leaves the browser except the analyze request.

### 10.5 Fallback copy (UI strings)
| Reason | Text shown under the method badge |
|---|---|
| `ml_disabled`, `forced_rules` | "Scored by the rule engine." |
| `model_loading` | "The AI model is still starting, so the rule engine scored this." |
| `model_error`, `model_timeout` | "The AI model was unavailable, so the rule engine scored this." |
| `unsupported_language` | "This text is not in a language the AI model supports, so the rule engine scored this." |
| `low_confidence`, `weak_class_uncertain`, `ambiguous_prediction` | "The AI model was not confident enough, so the rule engine scored this." |
| `ml_rule_disagreement` | "The AI model and the rule engine disagreed strongly, so the rule engine's score is shown." |

### 10.6 Debug view
`?debug=1` on the results page shows `rule_score`, `ml_score`, NOVA probabilities, latency, and a "Force rules" toggle (sends `force_mode: "rules"`). Used for the demo to show both paths.

## 11. Performance and demo reliability

| Item | Plan |
|---|---|
| Model load | Background thread at startup; API serves rule results with `model_loading` until ready |
| Dev loop | Single uvicorn worker; avoid `--reload` with ML on (it reloads the model on every save); `ML_ENABLED=false` while working on the UI |
| Optional speed-up | `torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)`; accept only if outputs on the 12-string sanity set and the golden set are unchanged in band |
| Latency targets | Rule path < 100 ms; ML path p95 < 2 s after warm-up (send one warm-up inference at startup) |
| Demo day | Pre-warm by sending one analyze request before presenting. Have `ML_ENABLED=false` ready as a safe mode, and a recorded demo video |
| Offline | Model folder is local; no network calls at runtime |

## 12. Testing strategy

| Layer | Tests (pytest) |
|---|---|
| Parser | Nested brackets, `(59%)`, `INS 500(ii)` inside brackets, `E211` vs `INS 211`, empty/very long input, 80-token cap, "Contains:" prefix |
| Matcher | Alias exact, fuzzy typo (`palm olien`), too-short strings rejected, unmatched neutral, coverage calculation |
| Rules | Each flag penalty, position multiplier boundaries (3/4, 6/7), sugar splitting, penalty cap, bonus cap, safety caps, profile multipliers, determinism |
| Gate | One test per reason code using a **mocked** `NovaModel` (no real model in unit tests): not ready, error, timeout, low confidence, NOVA-2 uncertain, small margin, optimistic gap, pessimistic gap, skipped checks at low coverage, ML accepted |
| Orchestrator | Insufficient input, not food, forced rules, ML exception never 500s |
| API | Response schema (Pydantic), status codes, CORS headers, `/health` |
| Fault injection | Kill the model mid-run, return garbage probabilities (NaN, not summing to 1): must fall back with `model_error` |
| Golden set | `scripts/eval_golden.py` prints a table: product, expected band, rule band, ML band, method used, reason. Targets: ML-vs-rule band agreement >= 75%, ML path used on >= 70% of products, no crashes |
| Frontend | Manual checklist in `docs/PRD.md` section 12. Automated tests (vitest) only for pure functions in `src/lib` (tracker math, history cap, query-param prefill) |
| Nutri-Score | At least 30 validation vectors (16.2); missing-input and assumption paths; category detection; unit conversions |
| Hindi | Cases listed in 16.4; no missing i18n keys in either language |
| Extension | Extractor fixtures with jsdom plus the manual checklist in 16.6 |

Deterministic rule tests must not depend on the model or network.

## 13. Security, privacy, licensing
- `joblib.load` executes pickle code. Load only from the pinned revision in a project-controlled folder; never load user-supplied files.
- No PII stored server-side. History/profile stay in the browser. Do not log full ingredient text at INFO.
- Input validation: max 4000 chars, plain text only, no HTML rendering of user input (React escapes by default; never use `dangerouslySetInnerHTML`).
- Licences: Open Food Facts data under ODbL (attribution shown in README and app footer); model Apache-2.0.
- Health disclaimer visible on the results page.
- Extension: minimal permissions, no always-on content scripts, user-initiated extraction only, no analytics. `CORS_ORIGIN_REGEX` for extensions is a development setting and must stay off for any hosted deployment.
- Nutri-Score: do not use the official logo; label the grade as computed by NutriSnap and not an Indian standard.
- Deep link `?ingredients=`: treat as plain text, cap at 4000 characters, never render as HTML.

## 14. Folder structure
```
nutrisnap/
  README.md
  docs/
    PRD.md
    ARCHITECTURE.md
    decisions.md                 # spike result, thresholds chosen, known issues
  design/refs/                   # optional reference images added by the owner
  backend/
    app/
      main.py
      config.py                  # pydantic-settings, all env vars
      schemas.py
      api/routes.py
      core/
        parser.py  normalizer.py  matcher.py  knowledge_base.py
        rules.py   personalization.py  gate.py  scoring.py
        nova_badge.py  nutriscore.py  language.py
        ml/ base.py  hf_nova.py  minilm_head.py
      data/
        kb/ingredients.json  category_rules.json  category_notes.json
        vocab/common_ingredients.txt  common_ingredients_hi.txt
        golden/golden_products.json
        nutriscore/nutriscore_2023.json
        daily_targets.json
    models/                      # git-ignored (model downloads)
    notebooks/ nova_spike.ipynb  train_head_colab.ipynb
    scripts/ download_model.py  eval_golden.py  eval_nova_india.py
    tests/
    requirements.txt
    .env.example
  frontend/
    src/ pages/ components/ hooks/ lib/ styles/ i18n/ (en.json, hi.json) tracker/ report/
    tailwind.config.js  vite.config.js  package.json  .env.example
  extension/                     # Chrome/Edge MV3 (section 16.6)
  .gitignore
```

## 15. Decisions log

| ID | Decision | Reason |
|---|---|---|
| ADR-1 | No Postgres/Redis/Docker/pgvector/semantic matching in Release 1 | Not needed for the demo: the KB is a small JSON file, history and tracker live in the browser, fuzzy matching is enough. Revisit for multi-device sync or hosting |
| ADR-2 | ML predicts NOVA (processing level), rules score ingredient-level health flags | NOVA has a ready pretrained model and lots of labelled data; no pretrained model scores "harm" |
| ADR-3 | Rule engine is always computed | Needed for fallback, disagreement check, transparency, and as the demo safety net |
| ADR-4 | Pinned HF revision, local model folder | Reproducibility, offline demo, pickle safety |
| ADR-5 | Asymmetric disagreement thresholds | False reassurance costs more than false caution in a health tool |
| ADR-6 | One `primary_flag` per KB entry | Prevents double counting and keeps scoring explainable |
| ADR-7 | Explanations are display-only and must be sourced | Avoids fabricated health claims |
| ADR-8 | Spike before commit; Plan B ready | Plan A has an integration gap and no independent validation |
| ADR-9 | Extras sit behind feature flags with acceptance tests | 3-day deadline: an unfinished extra must be hidden, not half-working |
| ADR-10 | NutriSnap score, NOVA badge and Nutri-Score are separate signals, never averaged | They measure different things and can legitimately disagree |
| ADR-11 | PDF export via browser print, not a PDF library | Devanagari shaping and font embedding are reliable in the browser and fragile in PDF libraries |
| ADR-12 | Tracker, history and profile stay client-side | No accounts or server storage needed; privacy by default. Extension and web app therefore do not share history (deep link bridges them) |
| ADR-13 | Nutri-Score thresholds transcribed from the official specification and validated before enabling | Memory-typed thresholds would be an unverifiable health claim; 2017 and 2023 algorithms differ |

---

## 16. Feature modules (extras)

Each module sits behind a feature flag and has its own acceptance tests (`docs/PRD.md` section 6). Build order and go/no-go gates: `docs/PRD.md` section 10.

| Flag | Where | Default | Controls |
|---|---|---|---|
| `VITE_FEATURE_NOVA_BADGE` | frontend | true | NOVA badge card |
| `VITE_FEATURE_EXPORT` | frontend | true | PDF export button and print routes |
| `FEATURE_NUTRISCORE` / `VITE_FEATURE_NUTRISCORE` | backend / frontend | false | Nutrition form and Nutri-Score card. Enable only after the validation in 16.2 passes |
| `VITE_FEATURE_TRACKER` | frontend | false | Daily tracker page and "Log this product" button (needs the nutrition form) |
| `VITE_FEATURE_HINDI` | frontend | false | Language toggle and Hindi UI strings |
| `ML_HINDI_SUPPORTED` | backend | false | Whether Hindi-dominant text may be sent to the ML model (set true only if the spike shows it works) |

`GET /api/health` reports backend flags under `features`. The UI shows a feature only if both sides allow it.

**Three separate signals, never averaged.** The NutriSnap score (ingredients plus processing), the NOVA badge (processing only) and the Nutri-Score grade (nutrients only) answer different questions and can disagree, for example a product with plain ingredients but very high sugar. The results page shows them in separate cards with a one-line explanation each. FSSAI's own front-of-pack proposal is nutrient-based and treats nutrition and processing as separate concepts (reported September 2026; check the current status before quoting it in the project report).

### 16.1 NOVA badge

Module `app/core/nova_badge.py`. Pure function of the scoring result.

| Condition | Badge |
|---|---|
| `scoring_method == "ml_assisted"` | `{group: nova.top, source: "model", confidence}` |
| Rule fallback and at least one matched flag in `{flavour_enhancer, artificial_sweetener, synthetic_colour, emulsifier_stabiliser, flavour_additive, ultra_processing_marker, trans_fat_source}` | `{group: 4, source: "rule_estimate", basis: [flags]}` |
| Anything else | `{group: null, source: "unavailable"}` (rules cannot reliably tell NOVA 1-3 apart, so do not guess) |

Labels (from the model card's NOVA definitions): 1 Unprocessed or minimally processed, 2 Processed culinary ingredient, 3 Processed food, 4 Ultra-processed food. UI: a pill with tooltip, suffix "(rule-estimated)" when `source == "rule_estimate"`, and the note "NOVA describes the extent of industrial processing, not nutrient content."

Tests: each branch; marker list is data (`category_rules.json: nova_markers`), not hard-coded.

### 16.2 Nutrition facts and Nutri-Score grade

**Purpose.** A nutrient-based grade computed from the label's nutrition table, independent of the NutriSnap score. Indian packs declare nutrition information per 100 g/ml (and per serve), so inputs are usually on the pack.

**Input** (`nutrition`, optional in `POST /api/analyze`; always per 100 g or per 100 ml):
```json
{
  "basis": "per_100g",
  "category": "food",
  "energy_kcal": 450, "protein_g": 9, "carbohydrate_g": 62, "sugars_g": 3, "added_sugars_g": null,
  "fat_g": 18, "saturated_fat_g": 8, "trans_fat_g": 0, "fibre_g": 2, "sodium_mg": 1100,
  "fruit_veg_legume_nut_pct": null,
  "serving_size_g": 70
}
```
(illustrative values). `category` is `food` (default), `beverage` or `fat_oil_nut_seed`; the user picks it in the form. Validation: all numbers >= 0; `sugars_g <= carbohydrate_g`; `saturated_fat_g <= fat_g`; if `carbohydrate_g + fat_g + protein_g > 105` return a warning `nutrition_inconsistent` (still compute).

**Conversions.** `energy_kj = energy_kcal * 4.184`. `salt_g = sodium_mg * 2.5 / 1000`.

**Algorithm.** Implement the **2023 update** of the Nutri-Score algorithm (in use in Nutri-Score countries since 2024) for the three categories: general foods, fats/oils/nuts/seeds, beverages. Module `app/core/nutriscore.py`; thresholds in `app/data/nutriscore/nutriscore_2023.json` with `source` and `retrieved_on` fields.
- **Do not type thresholds from memory.** Transcribe them from the official specification published by the Nutri-Score Scientific Committee (the 2022 update report and the final 2023 algorithm; the 2024 Nature Food paper's supplementary tables are a cross-check) or from Santé publique France's official calculator documentation. The 2017 and 2023 algorithms differ (stricter sugar and salt scales, a different energy treatment, different handling of beverages including milk and plant drinks, and sweeteners); never mix them.
- Beverage sweetener handling uses the `artificial_sweetener` flag from the matcher, as the specification requires.
- Total points = negative components minus positive components; letter grade from the category's threshold table in the JSON.

**Missing inputs.** Required (cannot be assumed): energy, sugars, saturated fat, sodium or salt. Fibre, protein and fruit/veg/legume/nut share may be undeclared on Indian labels: assume 0, list them in `assumptions`, and warn that the grade may be understated.

**Output** (`nutriscore` in the analyze response; values illustrative):
```json
{
  "status": "computed",
  "grade": "D",
  "points": 14,
  "algorithm": "2023",
  "category": "food",
  "components": {
    "negative": {"energy": 5, "sugars": 1, "saturated_fat": 6, "salt": 6},
    "positive": {"fibre": 1, "protein": 3, "fruit_veg": 0}
  },
  "assumptions": ["fruit_veg_legume_nut_pct not declared; assumed 0"],
  "warnings": []
}
```
Other statuses: `{"status": "missing_inputs", "missing": ["sugars_g", "sodium_mg"]}`, `{"status": "disabled"}`, `{"status": "not_provided"}`.

**Validation protocol (gate for enabling `FEATURE_NUTRISCORE`).** Build at least 30 test vectors across the three categories from (a) examples in the official specification or calculator, and (b) Open Food Facts products where the dataset exposes a grade computed with the same algorithm version (inspect the dataset's field names and versions first). Pass criteria: at least 90% exact grade match and 100% within one grade. Otherwise ship with the flag off and say so in the report.

**Branding.** Do not use the official Nutri-Score logo. Show a neutral A-E scale labelled "Nutri-Score grade (computed by NutriSnap with the published algorithm)" and check the scheme's usage conditions before any use of its logo.

**India context.** Nutri-Score is a European scheme and not an Indian standard. FSSAI's front-of-pack plan is still before the Supreme Court: the 2022 draft proposed an Indian Nutrition Rating (star scale); in 2026 FSSAI moved to a red-hexagon warning proposal ("High Sugar / High Salt / High Fat") with thresholds based on the ICMR-NIN 2024 dietary guidelines, and the thresholds were not final when this document was written. The UI shows the note "European reference grade, not an Indian standard." Future option, out of scope now: FSSAI-style warning chips once thresholds are notified.

### 16.3 Daily cumulative tracker

**Purpose.** Turn single scans into a daily picture: how much sugar, saturated fat, trans fat and sodium the user has logged from packaged items today against general limits. All client-side; no server state, no account.

**Entry creation.** On the results page, "Log this product" opens a dialog: serving size (g), servings (default 1), and per-100 g nutrition (prefilled from the nutrition form if present; otherwise minimum fields are energy, sugars, saturated fat, sodium). "Log without nutrients" is allowed and counts as "no data".

**Storage** (`localStorage` key `nutrisnap.tracker.v1`, max 1000 entries; values illustrative):
```json
{
  "settings": {"profile": "who", "energy_reference_kcal": 2000},
  "entries": [
    {
      "id": "uuid", "loggedAt": "2026-10-21T08:30:00+05:30", "title": "Instant noodles",
      "scanId": "uuid-or-null", "servings": 1, "serving_size_g": 70,
      "per100g": {"energy_kcal": 450, "sugars_g": 3, "added_sugars_g": null, "saturated_fat_g": 8, "trans_fat_g": 0, "sodium_mg": 1100, "fibre_g": 2, "protein_g": 9},
      "totals":  {"energy_kcal": 315, "sugars_g": 2.1, "saturated_fat_g": 5.6, "trans_fat_g": 0, "sodium_mg": 770, "fibre_g": 1.4, "protein_g": 6.3}
    }
  ]
}
```
**Calculations** (pure functions in `frontend/src/lib/tracker.js`):
- `totals[n] = per100g[n] * serving_size_g / 100 * servings`, rounded to 1 decimal. `null` stays `null` (missing, never treated as 0) and increments a `missing_count` shown in the UI.
- Day key = local calendar date of `loggedAt` in the browser time zone.
- Daily limits come from `app/data/daily_targets.json` (Appendix E), served to the frontend as a static copy. Default profile `who`: free sugars below 10% of energy (with a 5% stretch marker), saturated fat below 10% of energy, trans fat below 1% of energy, sodium below 2000 mg. Energy reference defaults to 2000 kcal and is user-editable.
- Sugar nutrient: use `added_sugars_g` if every entry that day has it, otherwise `sugars_g` and label the bar "approximate (includes naturally occurring sugars)".
- Progress colour: below 70% of the limit `primary`, 70-100% `secondary`, above 100% `tertiary`.
- A second target profile `icmr_nin_2024` exists in the JSON but is `enabled: false` until the owner fills and verifies the values from the guideline document.

**Views.** Today (one progress card per nutrient: "x of y unit"), entries list (edit servings, delete), last-7-days bar chart with the limit line, empty state, settings drawer (energy reference, target profile), "Clear all data". Text on the page: "Tracks only the packaged items you log, not your whole diet. Targets are general guidelines, not personal medical advice."

**Tests** (vitest, pure functions only): totals and rounding, null handling, day grouping across midnight, threshold colours at 69/70/100/101%, sugar fallback, 1000-entry cap.

### 16.4 Hindi support

**Scope.** (a) Hindi UI, (b) Hindi and bilingual ingredient lists as input, (c) Hindi ingredient explanations when available. Response labels stay codes plus English; the frontend translates codes.

**Backend (`app/core/language.py`, parser and matcher changes)**
- Normalization for matching: Unicode NFC; remove zero-width joiners (U+200C, U+200D); remove the nukta (U+093C) for comparison only; map Devanagari digits (U+0966-U+096F) to ASCII digits; treat the danda (U+0964) as a separator like `,`.
- `devanagari_ratio` = Devanagari letters / all letters. Mode: `latin` (< 0.2), `devanagari` (> 0.8), otherwise `mixed`.
- KB entries gain optional `aliases_hi` and `aliases_hinglish` (Appendix D). Both are added to the alias index at load time. Fuzzy cutoff for Devanagari tokens is 90 and minimum length 3 characters.
- **Bilingual labels** list every ingredient twice. The rule engine counts each `kb_id` once (section 6.3), so penalties are not doubled.
- **ML input** = Latin-script tokens joined with ", ". If fewer than 2 Latin tokens remain and `ML_HINDI_SUPPORTED=false`, skip ML with reason `unsupported_language`. The model card lists 7 languages without naming them, so the spike (7.2) must test a small Hindi set before setting the flag true.
- `looks_like_food` also reads `app/data/vocab/common_ingredients_hi.txt` (generic Hindi food words only).
- Response adds `language: {"detected": "mixed", "ml_input": "latin_only"}`. `lang` in the request selects `explanation_hi` / `swap_tip_hi` where present; otherwise English text is returned with `explanation_lang: "en"`.

**Frontend**
- `react-i18next`, files `src/i18n/en.json` and `src/i18n/hi.json`; language toggle in the top bar; stored in `nutrisnap.lang.v1`; set `<html lang>`.
- Keys cover: nav, form labels, band names, flag labels (`flags.<code>`), fallback reasons (`reasons.<code>`, section 10.5), statuses and error messages, disclaimer, tracker, report.
- Fonts: bundle `@fontsource/noto-sans-devanagari` (weights 400, 500, 700) next to Inter so Devanagari renders offline and in print. Add `"Noto Sans Devanagari"` to the Tailwind `fontFamily.sans` stack after Inter; use slightly larger line height for `lang="hi"`.
- **Review gate.** Hindi strings drafted by the coding agent are marked `"_meta": {"reviewed": false}` in `hi.json` and `translation_verified: false` in the KB. A fluent reader must review them before the demo. Do not present unreviewed Hindi health text as verified.

**Tests.** Hindi-only list, bilingual list (no double penalty), mixed script, Devanagari digits in percentages, danda separator, nukta variants of the same word, `unsupported_language` fallback, UI renders every key in both languages (no missing-key warnings).

### 16.5 PDF export

**Approach: browser print to PDF from a dedicated report route.** No server-side PDF library, for three reasons: WeasyPrint needs Pango/GTK (painful on Windows), ReportLab does not shape Devanagari, and jsPDF needs manual font embedding and also does not shape Devanagari. The browser shapes all scripts and embeds fonts.

- Routes: `/report/:id` (history item id, or `current`) and `/report/tracker?from=YYYY-MM-DD&to=YYYY-MM-DD`.
- "Export PDF" opens the report route in a new tab, waits for `document.fonts.ready`, sets `document.title = "NutriSnap-<product>-<yyyy-mm-dd>"` (Chrome uses it as the default file name), then calls `window.print()`.
- Print CSS: `@page { size: A4; margin: 14mm; }`; force a light theme in `@media print` (white background, dark text) while keeping band colours legible; `print-color-adjust: exact` for the score ring; hide nav and buttons; `break-inside: avoid` on cards and table rows.
- **Scan report contents:** header (NutriSnap, date and time), product title, score ring, band, scoring method and fallback reason, NOVA badge, Nutri-Score card if computed, flags, ingredient table (position, name, matched, flag, points, explanation if verified), profile effects, the original ingredient text, disclaimer, attribution, footer with app version, KB version and model id with revision.
- **Tracker report contents:** date range, per-day totals vs limits, entries table, note on scope and missing data.
- Acceptance: Chrome "Save as PDF" yields 1-2 A4 pages for a typical scan, text is selectable, Hindi renders correctly, no clipped content, footer present.

### 16.6 Browser extension (Chrome / Edge, Manifest V3)

**Purpose.** Analyze ingredient text on the page you are browsing (retailer product pages, brand sites) without copy-paste between tabs.

```
extension/
  manifest.json
  service_worker.js
  popup/ popup.html  popup.js  popup.css
  content/ extract_ingredients.js  selectors.json
  options/ options.html  options.js
  lib/ api.js  render.js
  icons/ 16.png 48.png 128.png
  README.md
  test/fixtures/*.html  test/extract.test.mjs
```
No build step: plain ES modules.

**Manifest.** `manifest_version: 3`; `permissions`: `contextMenus`, `activeTab`, `scripting`, `storage`; `host_permissions`: `http://localhost:8000/*`; `optional_host_permissions`: `https://*/*`, `http://*/*` (requested at runtime from the options page only when the user sets a different API URL); `action.default_popup`; `background.service_worker` with `type: "module"`. **No always-on content scripts**: the extractor is injected on demand with `chrome.scripting.executeScript` after a user action.

**Flows**
1. **Context menu.** Select text, right-click "Analyze selection with NutriSnap". The service worker calls the API, then sets the toolbar badge to the score (colour by band) and stores the last result in `chrome.storage.session`. Opening the popup shows that result. (Chrome cannot reliably open the popup programmatically, so the badge is the signal.)
2. **Popup.** Textarea prefilled with the last selection. "Extract from this page" injects `extract_ingredients.js` into the active tab and fills the textarea. "Analyze" calls `POST /api/analyze` and renders a compact card: score ring, band, method badge, NOVA badge, top three flags, disclaimer. "Open full report" opens `${APP_URL}/?ingredients=<urlencoded>&autorun=1`; the web app prefills the Scan page and runs the analysis, which saves it to the web app's history.
3. **Options page.** API URL (default `http://localhost:8000`), app URL (default `http://localhost:5173`), language, health conditions. Stored in `chrome.storage.local`.

**Extraction heuristic (`extract_ingredients.js`).** Priority: (1) the user's current text selection; (2) elements whose own text matches `^(ingredients?|सामग्री)\b[:\s-]*` (case-insensitive): take the remainder of that element or the next sibling's text; (3) optional per-site selectors from `selectors.json` for two or three retailers the owner chooses and verifies by hand (these break when sites change). Stop at the next heading-like element (Nutrition, Allergen, Storage, Directions) or after 2000 characters. Return `{text, method}`. Runs only after a user click; the extension never crawls or reads pages in the background.

**Backend.** Extension pages with `host_permissions` can call the API without CORS. As a fallback for development, `CORS_ORIGIN_REGEX=^chrome-extension://.*$` can be set; never enable it on a hosted deployment because it lets any installed extension call the API.

**Web app support.** `ScanPage` reads `?ingredients=` (max 4000 characters, URL-decoded, treated as plain text) and `autorun=1`.

**Limits (state them in the extension README).** Needs a running backend (localhost for the demo). History and profile are separate from the web app because each has its own storage; the deep link is the bridge. Retailer layouts change, so the heuristic is best effort. Chrome and Edge only; loaded unpacked, no store listing.

**Tests.** `extract.test.mjs` runs the extractor against the HTML fixtures with jsdom (selection, "Ingredients:" prefix, heading plus sibling, Hindi heading, stop at "Nutrition"). Manual checklist: context menu on 3 pages, popup extract on 3 pages, options change of API URL with permission prompt, backend down shows a clear error, language toggle.

---

## Appendix A - Seed knowledge base (names and flags only)

The agent creates these entries with `explanation`, `swap_tip`, `source` = `null` and `verified` = `false`, and may add aliases. Flags are classification, not health claims. INS numbers are from the Codex/FSSAI numbering; the owner verifies each before the demo.

| Canonical | Example aliases | INS | primary_flag |
|---|---|---|---|
| Sugar | sugar, cane sugar, refined sugar, sucrose | - | added_sugar |
| Glucose syrup | glucose syrup, glucose solids | - | added_sugar |
| High fructose corn syrup | hfcs, glucose-fructose syrup, fructose syrup, corn syrup | - | added_sugar |
| Invert sugar syrup | invert sugar, invert syrup | - | added_sugar |
| Dextrose | dextrose, glucose | - | added_sugar |
| Refined wheat flour | maida, refined wheat flour, wheat flour (maida), all purpose flour | - | refined_flour |
| Wheat flour (unspecified) | wheat flour | - | refined_flour (owner to confirm; label wording is ambiguous) |
| Hydrogenated vegetable fat | hydrogenated vegetable oil, hydrogenated vegetable fat, partially hydrogenated oil, vanaspati | - | trans_fat_source |
| Palm oil | palm oil, palmolein, palm olein, refined palm oil, palm kernel oil | - | saturated_fat_source |
| Salt | salt, iodised salt, common salt, sodium chloride | - | sodium_source |
| Monosodium glutamate | msg, monosodium glutamate, flavour enhancer 621 | 621 | flavour_enhancer |
| Disodium guanylate | disodium guanylate | 627 | flavour_enhancer |
| Disodium inosinate | disodium inosinate | 631 | flavour_enhancer |
| Disodium 5'-ribonucleotides | disodium ribonucleotides | 635 | flavour_enhancer |
| Sodium benzoate | sodium benzoate | 211 | preservative |
| Potassium sorbate | potassium sorbate | 202 | preservative |
| Sorbic acid | sorbic acid | 200 | preservative |
| Calcium propionate | calcium propionate | 282 | preservative |
| Sodium metabisulphite | sodium metabisulphite | 223 | preservative |
| TBHQ | tbhq, tertiary butylhydroquinone | 319 | preservative |
| BHA | bha, butylated hydroxyanisole | 320 | preservative |
| BHT | bht, butylated hydroxytoluene | 321 | preservative |
| Aspartame | aspartame | 951 | artificial_sweetener |
| Acesulfame potassium | acesulfame k, acesulfame potassium | 950 | artificial_sweetener |
| Sucralose | sucralose | 955 | artificial_sweetener |
| Saccharin | saccharin | 954 | artificial_sweetener |
| Tartrazine | tartrazine | 102 | synthetic_colour |
| Sunset yellow FCF | sunset yellow | 110 | synthetic_colour |
| Carmoisine | carmoisine, azorubine | 122 | synthetic_colour |
| Ponceau 4R | ponceau 4r | 124 | synthetic_colour |
| Allura red | allura red | 129 | synthetic_colour |
| Brilliant blue FCF | brilliant blue | 133 | synthetic_colour |
| Mono- and diglycerides | mono and diglycerides of fatty acids, emulsifier (471) | 471 | emulsifier_stabiliser |
| Polysorbate 80 | polysorbate 80 | 433 | emulsifier_stabiliser |
| Carboxymethyl cellulose | cmc, cellulose gum | 466 | emulsifier_stabiliser |
| Artificial flavour | artificial flavouring substances, nature identical flavouring substances, added flavour | - | flavour_additive |
| Maltodextrin | maltodextrin | - | ultra_processing_marker |
| Modified starch | modified starch | 1404, 1412, 1414, 1422, 1442 | ultra_processing_marker |
| Hydrolysed vegetable protein | hydrolysed vegetable protein, hvp | - | ultra_processing_marker |
| Soy protein isolate | soy protein isolate | - | ultra_processing_marker |
| Whole wheat flour | whole wheat flour, atta, whole wheat atta, multigrain atta | - | whole_grain_or_fibre |
| Oats | oats, rolled oats, whole oats | - | whole_grain_or_fibre |
| Ragi | ragi, finger millet, nachni | - | whole_grain_or_fibre |
| Jowar | jowar, sorghum | - | whole_grain_or_fibre |
| Bajra | bajra, pearl millet | - | whole_grain_or_fibre |
| Brown rice | brown rice | - | whole_grain_or_fibre |
| Peanuts | peanuts, groundnuts | - | legume_nut_seed |
| Almonds | almonds | - | legume_nut_seed |
| Cashew | cashew, cashew nut | - | legume_nut_seed |
| Chana | chana, bengal gram, roasted gram, chickpea | - | legume_nut_seed |
| Moong / lentils | moong, dal, lentils | - | legume_nut_seed |
| Flax / sesame seeds | flax seeds, linseed, sesame | - | legume_nut_seed |

Jaggery, honey and "vegetable fat (unspecified)" are deliberately left out: the owner decides how to classify them after reading the sources.

### Category notes with citations (safe to ship)
Stored in `category_notes.json`, shown as category-level context. The owner re-checks each citation before the demo.

| Flag | Note | Source |
|---|---|---|
| added_sugar | WHO recommends keeping free sugars below 10% of total energy intake, with further benefit below 5%. | WHO, Guideline: Sugars intake for adults and children (2015) |
| trans_fat_source | WHO recommends limiting trans-fat intake to less than 1% of total energy intake. | WHO, Saturated fatty acid and trans-fatty acid intake for adults and children (2023) |
| saturated_fat_source | WHO recommends limiting saturated fat to less than 10% of total energy intake. | Same WHO 2023 guideline |
| sodium_source | WHO recommends adults consume less than 2 g sodium per day (about 5 g salt). | WHO, Guideline: Sodium intake for adults and children (2012) |

## Appendix B - Golden set template

`backend/app/data/golden/golden_products.json` (owner fills 20 real products from packs at home; the agent must not invent ingredient lists for real brands):
```json
[
  {
    "name": "<product name as on pack>",
    "category": "instant noodles",
    "ingredients_text": "<copied exactly from the pack>",
    "expected_band": "High Risk",
    "note": "owner's judgment, one line why"
  }
]
```
Suggested spread: instant noodles, cream biscuits, potato chips, cola, packaged fruit juice, namkeen, rusk, bread, breakfast cereal, muesli/oats, peanut butter, roasted chana, whole-wheat atta, ketchup, chocolate spread, soya chunks, protein bar, plain biscuits, flavoured yoghurt drink, ready-to-eat curry mix. About 5 expected Low, 8 Moderate, 7 High.

## Appendix C - `.env.example`
```
ML_ENABLED=true
NOVA_BACKEND=hf_hsilvosa
NOVA_MODEL_DIR=backend/models/hsilvosa-nova
NOVA_MODEL_REVISION=f252e3546650954596ff7e5926aab4559c433909
ML_TIMEOUT_S=3.0
ML_MIN_CONFIDENCE=0.60
ML_NOVA2_MIN_CONFIDENCE=0.80
ML_MIN_MARGIN=0.15
ML_MAX_OPTIMISTIC_GAP=25
ML_MAX_PESSIMISTIC_GAP=45
SHOW_UNVERIFIED_BADGE=true
CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
FEATURE_NUTRISCORE=false
ML_HINDI_SUPPORTED=false
CORS_ORIGIN_REGEX=
```

Frontend `.env.example`:
```
VITE_API_URL=http://localhost:8000
VITE_FEATURE_NOVA_BADGE=true
VITE_FEATURE_EXPORT=true
VITE_FEATURE_NUTRISCORE=false
VITE_FEATURE_TRACKER=false
VITE_FEATURE_HINDI=false
```

## Appendix D - Hindi and Hinglish seed aliases

Agent-drafted starting point for `aliases_hi` and `aliases_hinglish`. **A fluent reader must verify every entry before the demo**; keep `translation_verified: false` until then. Add more only from real labels.

| KB entry | `aliases_hi` | `aliases_hinglish` |
|---|---|---|
| Sugar | चीनी, शक्कर | cheeni, chini, shakkar |
| Refined wheat flour | मैदा | maida |
| Whole wheat flour | गेहूं का आटा, साबुत गेहूं का आटा | gehu ka atta, atta |
| Salt | नमक | namak |
| Palm oil | पाम तेल, पामोलीन, पाम ऑयल | palm tel |
| Hydrogenated vegetable fat | वनस्पति, वनस्पति घी, हाइड्रोजनीकृत वनस्पति वसा | vanaspati |
| Peanuts | मूंगफली | moongfali |
| Oats | ओट्स, जई | oats, jai |
| Ragi | रागी, नाचनी | ragi, nachni |
| Chana | चना, भुना चना | chana |
| Sodium benzoate | सोडियम बेंजोएट | sodium benzoate |
| Monosodium glutamate | मोनोसोडियम ग्लूटामेट | msg |

`common_ingredients_hi.txt` (generic words for the `looks_like_food` check, no health claims): दूध, पानी, गेहूं, चावल, मसाले, तेल, आटा, दाल, मक्का, आलू, टमाटर, प्याज, लहसुन, हल्दी, मिर्च, जीरा, धनिया, अदरक.

## Appendix E - `daily_targets.json`

Structured fields only; no formula strings and no `eval`.

```json
{
  "version": 1,
  "default_profile": "who",
  "energy_reference_kcal": 2000,
  "profiles": {
    "who": {
      "label": "WHO-based general limits",
      "enabled": true,
      "targets": {
        "free_sugars_g":   {"energy_fraction": 0.10, "stretch_energy_fraction": 0.05, "kcal_per_g": 4,
                            "source": "WHO, Guideline: Sugars intake for adults and children (2015)"},
        "saturated_fat_g": {"energy_fraction": 0.10, "kcal_per_g": 9,
                            "source": "WHO, Saturated fatty acid and trans-fatty acid intake for adults and children (2023)"},
        "trans_fat_g":     {"energy_fraction": 0.01, "kcal_per_g": 9,
                            "source": "WHO, same 2023 guideline"},
        "sodium_mg":       {"value": 2000,
                            "source": "WHO, Guideline: Sodium intake for adults and children (2012)"}
      }
    },
    "icmr_nin_2024": {
      "label": "ICMR-NIN Dietary Guidelines for Indians 2024 (owner to fill and verify)",
      "enabled": false,
      "targets": {}
    }
  }
}
```
Derived at 2000 kcal: free sugars 50 g (stretch 25 g), saturated fat about 22 g, trans fat about 2.2 g, sodium 2000 mg. Target in grams = `energy_fraction * energy_reference_kcal / kcal_per_g`.
