# NutriSnap - Product Requirements Document

Version 1.1 - 2026-10-20 - Owner: Jeetpal - Deadline: **2026-10-23 (Friday)**
Companion documents: `README.md`, `docs/ARCHITECTURE.md` (formulas, API, folder layout, feature modules).
Coding agent: read `README.md`, then this file, then `docs/ARCHITECTURE.md`, then follow section 15.

---

## 1. Summary

NutriSnap tells an Indian shopper how healthy a packaged food is from its ingredient list. It returns a 0-100 score with a per-ingredient breakdown, a NOVA processing badge and safer-swap tips. The score is produced by a pretrained NOVA classifier from Hugging Face plus transparent ingredient rules, and **automatically falls back to rules alone** when the ML output is missing, unsure, or inconsistent. Planned extras: Nutri-Score grade, daily tracker, Hindi support, PDF export, browser extension.

## 2. Problem and context

- Indian consumers eat more packaged food but cannot easily judge labels: technical names, INS numbers, mixed English/Hindi text, no condition-specific guidance.
- Existing apps are global and nutrient- or product-database-driven; few handle Indian ingredients (maida, vanaspati, palmolein) or Hindi labels.
- FSSAI's front-of-pack labelling is still undecided (2022 star-rating draft, a 2026 move toward warning labels, Supreme Court proceedings). Until it lands, a transparent, explainable tool has room.
- Honest limits of the approach: NOVA measures processing, not harm; the pretrained model is lightly validated; the rule engine only knows ingredients in our knowledge base. The product design makes these limits visible instead of hiding them.

## 3. Goals, non-goals, success criteria

**Goals**
- G1. Explainable score from pasted ingredient text in under 2 seconds.
- G2. ML assists scoring, and rules take over automatically and visibly when ML cannot be trusted.
- G3. No fabricated health claims: every displayed explanation is sourced or hidden.
- G4. A demo that works offline and survives component failure.
- G5. Extras added only when they pass acceptance tests.

**Non-goals (this deadline):** accounts and cloud sync, hosted deployment, OCR from photos, barcode lookup, product comparison with real products, medical advice, FSSAI warning-label emulation.

**Success criteria (demo level)**
| ID | Criterion |
|---|---|
| S1 | 5 prepared ingredient lists give plausible score and band; ML path under 2 s after warm-up, rule path under 0.5 s |
| S2 | Fallback visibly triggers for: forced rules, low-confidence input, model unavailable. Correct reason text shown each time |
| S3 | Golden set (20 products): ML-vs-rule band agreement >= 75%, ML path used on >= 70% |
| S4 | No explanation shown as verified without a source; unverified text hidden in the demo build |
| S5 | Whole demo works with no internet |
| S6 | NOVA model evaluated on an Indian subset; metrics written in `docs/decisions.md` and the report |

## 4. Users and scenarios

| User | Scenario |
|---|---|
| Health-conscious shopper | Pastes a biscuit pack's ingredients in the aisle, sees "High Risk", reads why |
| Person managing diabetes or blood pressure | Sets a profile; added sugar or sodium sources weigh more; sees "Personalized for ..." |
| Hindi-reading family member (Release 2) | Switches to Hindi, pastes a bilingual label |
| Panel / evaluator | Asks "what if the model is wrong?"; presenter forces rules with `?debug=1` and shows both scores |

## 5. Scope and releases

| Release | Target | Contents |
|---|---|---|
| **1 (demo)** | 2026-10-23 | Core analyze flow, rule engine, ML-assisted scoring with automatic fallback, results UI, scan history, NOVA badge, PDF export. Profile personalization and swap tips if time |
| **2** | After the demo, or earlier if Release 1 is done ahead of schedule | Nutri-Score grade (+ nutrition form), daily tracker, Hindi support, browser extension |
| Stretch | Any time after P0 | Re-train classifier head on Indian products |
| 3 | Later | OCR, barcode, real product comparison, FSSAI-style warning chips, accounts and hosting |

Each Release 2 item is behind a flag (`docs/ARCHITECTURE.md` section 16) and is shown in the demo only if its acceptance tests pass.

## 6. Functional requirements

### 6.1 Core (Release 1)

**FR-1 Analyze text input.** `POST /api/analyze` accepts 1-4000 characters.
- AC: fewer than 2 tokens or fewer than 15 characters returns `status: insufficient_input`; text that does not look like food returns `not_food_text`; over 4000 characters returns HTTP 422.
- AC: response matches the schema in architecture section 9.2.

**FR-2 Parse and normalize.** Handles nested brackets, percentages, `INS`/`E` codes, "Contains:" prefixes, 80-token cap.
- AC: parser tests listed in architecture section 12 pass, including `Raising agents [INS 500(ii), INS 503(ii)]`.

**FR-3 Match against the knowledge base.** Exact alias, then fuzzy (cutoff 88). Unmatched ingredients are neutral and shown as "Not in our database".
- AC: KB contains all Appendix A seed entries; each has exactly one `primary_flag`.
- AC: `kb_coverage` is reported; below 0.60 the UI shows the low-coverage banner.

**FR-4 Rule engine.** Implements architecture 6.3 exactly, with dedupe, position weights, sugar-splitting penalty, caps and safety caps.
- AC: deterministic; every rule has a unit test; constants come from `category_rules.json`.

**FR-5 ML-assisted score.** Implements architecture 6.4 using the NOVA adapter chosen by the spike.
- AC: model loads in a background thread; `/api/health` reports `ml_status`; the response includes NOVA probabilities and latency.

**FR-6 Automatic fallback.** Implements the gate in architecture 7.3.
- AC: one test per reason code with a mocked model; garbage probabilities (NaN, not summing to ~1) fall back with `model_error`; an ML exception never produces HTTP 500.

**FR-7 Transparency.** Every result shows the scoring method and, for fallbacks, the reason text from architecture 10.5. `?debug=1` shows `rule_score`, `ml_score`, probabilities, latency and a "Force rules" toggle.
- AC: forcing rules changes `scoring_method` to `rule_based` with `forced_rules`.

**FR-8 Results screen.** Score ring, band, flag chips, expandable ingredient list, method badge, disclaimer.
- AC: follows the design brief (architecture 10.1) and the screen spec (10.2); handles null explanations without placeholder text; works at 360 px and 1280 px widths.

**FR-9 Scan history.** Saved to `localStorage` (max 50), searchable, deletable.
- AC: survives refresh; "Clear all" works; corrupted storage does not crash the app.

**FR-10 Health profile (P1).** Conditions: diabetes, hypertension, high cholesterol. Multipliers per architecture 6.2.
- AC: with the profile on, affected flags score worse by the configured multiplier and the UI lists `profile_effects`.

**FR-11 Swap tips (P1).** "See Safer Alternatives" opens ingredient-level tips.
- AC: only entries with a non-null, verified `swap_tip` are shown; otherwise the panel says no tips are available. No product names or images.

**FR-12 Disclaimer and attribution.** Visible on the results page and in the footer.
- AC: contains "not medical advice", the NOVA-is-processing note, and the Open Food Facts ODbL attribution.

### 6.2 Extras (Release 2; module specs in architecture section 16)

**E1 NOVA badge (Release 1).**
- AC: model source shows the predicted group with confidence; rule-estimate shows NOVA 4 with "(rule-estimated)" only when a marker flag is present; otherwise "unavailable"; tooltip explains NOVA.

**E2 PDF export (Release 1).**
- AC: "Export PDF" opens `/report/:id` and prints; Chrome "Save as PDF" gives 1-2 A4 pages, selectable text, footer with versions, light theme, no clipped content.

**E3 Nutrition form and Nutri-Score.**
- AC: validation protocol in 16.2 passes (>= 30 vectors, >= 90% exact, 100% within one grade) before `FEATURE_NUTRISCORE=true`; missing inputs and assumptions displayed; no official logo; "European reference grade" note shown.
- AC: if validation does not pass in time, the feature ships off and the report says so.

**E4 Daily tracker.**
- AC: logging a product with nutrition updates today's progress bars; null nutrients count as "no data"; day grouping uses local time; 7-day chart; "Clear all data"; scope note shown; vitest tests for the calculations pass.

**E5 Hindi support.**
- AC: toggle switches every UI string; Hindi-only and bilingual ingredient lists parse and match; bilingual lists are not double-penalized; ML is skipped with `unsupported_language` unless the spike confirmed Hindi support; Hindi strings flagged unreviewed until a fluent reader signs off; Devanagari renders in the app and in the PDF.

**E6 Browser extension.**
- AC: loads unpacked in Chrome and Edge; context-menu analysis sets the badge and the popup shows the result; "Extract from this page" works on three pages the owner picks; "Open full report" prefills and runs the analysis in the web app; clear error when the backend is down.

## 7. ML and fallback requirements

1. **Model.** Plan A `hsilvosa/nova-group-classifier` at the pinned revision; Plan B MiniLM encoder plus a head trained on Open Food Facts. Decision comes from the 2-hour spike (architecture 7.2). Record it in `docs/decisions.md`.
2. **No ML result is shown without passing the gate.** The gate and thresholds are in architecture 7.3.
3. **Evaluation before trust.** Run the Indian-subset evaluation (architecture 7.5): accuracy, macro-F1, per-class results, majority baseline, reliability table, and the fraction of rows the gate would reject.
4. **Honest claims.** Say "ML estimates processing level (NOVA)"; do not say the model detects harmful ingredients. State that NOVA labels in the source data come from Open Food Facts' own rule-based algorithm.
5. **Re-training (stretch).** Only after Release 1: retrain the classifier head on Indian products with frozen encoder embeddings (architecture 7.6) and report before/after metrics.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Rule path < 0.5 s; ML path p95 < 2 s after warm-up; first request after start may use `model_loading` fallback |
| Reliability | Any ML failure degrades to rules; no stack traces to the client |
| Offline | No runtime network calls; model and assets local |
| Privacy | No accounts; no server-side storage of user text; history, profile, tracker stay in the browser; do not log full ingredient text at INFO |
| Accessibility | Text contrast per design tokens; score ring has an accessible label; keyboard-operable accordion; language attribute set |
| Compatibility | Latest Chrome and Edge; desktop and 360 px mobile width |
| Maintainability | All scoring constants in JSON; feature flags for extras; tests run with one command |

## 9. UX: screens and design tasks

The UI is designed from the brief in `docs/ARCHITECTURE.md` section 10.1 and the screen spec in 10.2. No external design file is used.

| Screen | Release | Priority |
|---|---|---|
| Results | 1 | Highest: this is what the panel looks at |
| Scan (home) | 1 | High |
| History | 1 | Medium |
| Tracker, nutrition form, language/settings, extension popup, report (print) | 2 | Built from the same tokens and components |

**Owner design input (optional, 15 minutes):** after M4a, review the screenshots and say what to change, or drop reference images into `design/refs/`. Keep feedback concrete (colours, density, layout) so it becomes a token or component edit.

Content rules: Indian examples; no stock photos or fictional brands; never show placeholder health text.

## 10. Delivery plan

### 10.1 Honest assessment

Effort is agent-assisted work including your review time.

| Item | Hours | Risk | Release |
|---|---|---|---|
| Colab spike for the model (you) | 2 | High: undocumented integration | 1 |
| Core backend: parser, matcher, rules, ML adapter, gate, API, tests | 10-12 | High at ML integration | 1 |
| Core UI: scan, results, history, profile | 8-10 | Medium | 1 |
| KB source verification (you) | 3-4 | Medium: slow, cannot be automated | 1 |
| Golden set from real packs (you) | 2 | Low | 1 |
| NOVA badge | 1 | Low | 1 |
| PDF export | 2 | Low | 1 |
| Nutri-Score incl. validation | 5-7 | High: spec transcription and validation | 2 |
| Daily tracker (needs nutrition form) | 5-6 | Medium | 2 |
| Hindi support plus review | 6-8 | Medium: translation quality | 2 |
| Browser extension | 4-5 | Medium: page extraction is brittle | 2 |

Release 1 is about 30-36 hours of mixed work and already fills the three days. Release 2 adds roughly 20-26 hours. **All six extras cannot be finished and validated by 2026-10-23.** The flags and gates below make that safe: unfinished extras stay hidden instead of half-working.

### 10.2 Day plan

| Day | You | Coding agent | Gate |
|---|---|---|---|
| Tue 10-20 evening | Create repo and add the docs; run the Colab spike; start collecting golden-set labels from packs at home | M0 scaffold and config; M1 parser, normalizer, matcher, KB seed, tests | Spike decision (Plan A or B) by end of night |
| Wed 10-21 | Verify KB entries against sources; finish 20 golden products; write spike results in `decisions.md`; review the M4a screenshots and give design feedback | M2 rules, dedupe, caps, personalization, tests; M3 ML adapter, gate, orchestrator, API, tests; M4a frontend scaffold, tokens, Scan page | **G1 (Wed night):** `/api/analyze` works end to end in both modes with tests green. If not, drop every extra except the NOVA badge |
| Thu 10-22 | Tune constants on the golden set; rehearse; update the Review deck and SRS (features and stack); record a backup demo video | M4b Results, History, profile; M5 NOVA badge; M6 PDF export; M7 hardening: golden eval, fault injection, README check; tag **RC1** | **G2 (Thu 6 pm):** RC1 tagged. Feature freeze for Release 1 |
| Fri 10-23 | Morning checks: offline run, pre-warm, ML on and off, backup video; present | Bug fixes only | Demo |

If RC1 is ready early, start Release 2 in this order, each merged only when its acceptance tests pass: Nutri-Score (E3), tracker (E4), Hindi (E5), extension (E6). Anything unfinished stays flagged off and appears only under "Roadmap" in the demo.

### 10.3 Milestones for the coding agent

| M | Deliverable | Stop and show |
|---|---|---|
| M0 | Repo scaffold, config, feature flags, `/api/health`, `.env.example`, `requirements.txt` | Tree and health output |
| M1 | Parser, normalizer, matcher, KB seed (Appendix A), tests | Test report |
| M2 | Rule engine, personalization, dedupe, caps, tests | Test report and 5 sample scores |
| M3 | ML adapters, gate, orchestrator, `/api/analyze`, fault-injection tests | Curl outputs for ML, low confidence, forced rules, model down |
| M4a | Frontend scaffold, tokens, Scan page | Screenshot |
| M4b | Results, History, profile drawer, swap panel | Screenshots at 360 px and 1280 px |
| M5 | NOVA badge (backend and UI) | Screenshot of all three badge sources |
| M6 | PDF export | Saved PDF |
| M7 | Hardening: golden eval, fault injection, docs check | Golden table and RC1 tag |
| M8 | Nutrition form and Nutri-Score (flagged) | Validation report |
| M9 | Tracker (flagged) | Screenshots and tests |
| M10 | Hindi (flagged) | Hindi screenshots, test report |
| M11 | Extension | Walkthrough of the manual checklist |

## 11. Owner tasks (content and data, cannot be delegated to the agent)

1. **Spike (2 h):** run `nova_spike.ipynb` in Colab; write the result and the Plan A/B decision in `docs/decisions.md`.
2. **KB verification (3-4 h):** for at least 30 seed entries write a short plain-language explanation and a source (FSSAI, ICMR-NIN, WHO, or peer-reviewed), set `verified: true`. Entries you cannot source stay unverified and hidden.
3. **Golden set (2 h):** 20 real packs, ingredient text copied exactly, expected band with a one-line reason (architecture Appendix B).
4. **Indian-subset evaluation (1 h):** run `eval_nova_india.py` in Colab; record metrics.
5. **Release 2 only:** 30 Nutri-Score validation vectors; Hindi review by a fluent reader; three retailer pages chosen for extension testing; ICMR-NIN 2024 targets if you want that profile.
6. **Report and deck:** update the SRS and Review deck for the final feature set.

## 12. Test and demo checklist

**Manual UI checklist (Release 1)**
- [ ] Paste a high-risk list (instant noodles), a moderate list, a low-risk list: sensible score, band, flags
- [ ] Paste gibberish: `not_food_text`; paste "sugar": `insufficient_input`
- [ ] Ingredient with a typo ("palm olien") still matches
- [ ] Unknown ingredient shows "Not in our database" and does not crash
- [ ] Method badge shows AI-assisted on a clear case; rule-based with correct reason on forced rules, low confidence, and with the model stopped
- [ ] `?debug=1` shows both scores
- [ ] Profile on: scores move as expected; "Personalized for" badge shown
- [ ] History: save, search, delete, refresh persistence
- [ ] PDF export: 1-2 pages, footer, light theme
- [ ] Offline: disconnect network, run the whole flow
- [ ] 360 px and 1280 px layouts
- [ ] Disclaimer and attribution visible

**Release 2 additions:** Nutri-Score card and missing-input state; tracker log/edit/delete/7-day chart; Hindi toggle on every screen and in PDF; extension context menu, popup extract, deep link, backend-down error.

**Demo script (6 minutes):** problem (30 s); paste a high-risk Indian product (60 s); explain score, flags, NOVA badge (60 s); force rules and show both scores and the fallback reason (60 s); profile personalization (45 s); export PDF (30 s); architecture and honest limits slide: processing vs nutrition, model validation on Indian data, unverified entries hidden (75 s).

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Plan A model integration fails (missing helper class, unknown pooling) | No pretrained ML | 2-hour time-box, then Plan B (MiniLM + own head, trained in Colab) |
| Model weak on Indian products or over-confident | Bad scores | Indian-subset evaluation; gate thresholds tuned; rules as authority on disagreement; honest reporting |
| KB verification takes longer than planned | Few verified explanations | Hide unverified text; score still works from flags; verify the most common ingredients first |
| Rules too lenient when KB coverage is low | False reassurance | Coverage warning; disagreement checks skipped at low coverage; safety caps |
| Scope creep from extras | Core not finished | Flags, gates G1/G2, extras only after RC1 |
| Nutri-Score thresholds mistyped | Wrong grades | Transcribe from the official spec, validate on >= 30 vectors, flag off if not validated |
| Hindi translation errors in health text | Misleading content | Review gate; unreviewed Hindi marked and not presented as verified |
| Retailer page changes break extraction | Extension fails on a site | Selection and manual paste always work; selectors are optional; test on chosen pages only |
| Demo machine or model fails | No ML on stage | `ML_ENABLED=false` safe mode, pre-warm, recorded video |
| Pickle load risk from the model repo | Code execution | Pinned revision, project-controlled folder, never load user files |
| Health liability | Reputational | Disclaimers; no medical claims; sourced content only |

## 14. Assumptions and open questions

**Assumptions:** 2026-10-23 is the final presentation (PPT, live demo, functionality and completion check), where the core must work properly and not every feature needs to be integrated; the UI is designed from the brief in architecture 10.1; Windows with Python 3.10+, Node 18+ and Chrome/Edge are available; hardware is not a constraint; Open Food Facts data and the model licences allow this use with attribution.

**Open questions (answers change the plan):**
1. (Resolved) The 23rd is the final presentation with a PPT, a live demo, functionality and a completion check. The core must work; extras may be missing. Release 1 in section 5 is the target.
2. Is this solo or a team? A team can parallelize KB verification, Hindi review and extension work.
3. Will a fluent Hindi reader review the Hindi strings and aliases before any demo of that feature?
4. Which three retailer pages should the extension target?

## 15. Working agreement for the coding agent

1. Read `README.md`, this file, then `docs/ARCHITECTURE.md`. The architecture document wins on formulas, constants, API shapes and folder layout.
2. Work milestone by milestone (10.3). **Stop after each milestone**, show the evidence listed, and wait for review.
3. **Never invent health claims.** Create KB entries with `explanation`, `swap_tip` and `source` set to `null` and `verified` set to `false`. The owner fills them. Never write ingredient lists for real brands; the owner supplies them.
4. **Never type Nutri-Score thresholds from memory.** Transcribe from the official specification, record the source in the JSON, and validate before enabling.
5. Do not add dependencies beyond those named in the README and architecture without asking. After the first successful install, freeze exact versions in `requirements.txt` and `package-lock.json`.
6. Use Tailwind 3.4 installed via npm, no CDN scripts. Implement the design brief in architecture 10.1 as tokens in `tailwind.config.js`; components use token names, never hard-coded colours.
7. Keep every extra behind its feature flag. Unfinished or unvalidated features must be hidden, not partially visible.
8. An ML failure must never return HTTP 500; it must return a rule-based result with a reason code.
9. Write tests with each milestone and run them before reporting. For UI milestones, open the app in the built-in browser and check it at 360 px and 1280 px before reporting. Use a mocked model in unit tests; never download the real model in tests.
10. Commit once per milestone with a clear message. Record decisions, thresholds chosen and known issues in `docs/decisions.md`.
11. If a step is blocked or the specification is ambiguous, ask instead of guessing. Report deviations from the architecture explicitly.
