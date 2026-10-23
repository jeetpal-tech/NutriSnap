# NutriSnap: full-stack repair and release prompt

You are working inside my existing NutriSnap repository. Implement and verify the repairs below; do not merely provide advice, a mockup, or another plan. Deliver a coherent, working application, not a dashboard about its implementation.

## 1. Product intent and working agreement

NutriSnap helps shoppers understand packaged-food ingredient labels, with an Indian-market focus: camera/upload or pasted ingredients, clear ingredient explanations, a cautious assessment, useful generic alternatives, and private scan history. The original project discussion emphasized ingredient normalization, OCR, an evidence-based knowledge base, and optional personalization. It did not request a public database explorer.

When I said my professor would ask about database schemas and queries, I meant the implementation must be sound and explainable. Keep that material in developer documentation and local tools, never in the shopper experience.

First read AGENTS.md, README.md, docs/PRD.md, docs/ARCHITECTURE.md, docs/HANDOFF.md, docs/DATABASE.md, and relevant decisions/tests. Inspect git status and the actual implementation. Preserve unrelated changes, existing data, model artifacts, and backend-only credentials.

This request explicitly supersedes conflicting old requirements about the soft rounded UI, public database/debug screens, browser-only history, and no external API calls. Preserve scoring safety rules, content safeguards, and model validation gates. Reconcile contradictory documentation rather than blindly following outdated milestones. For this repair, proceed through bounded implementation and verification stages without waiting for review after every stage. Ask only for a genuinely blocking credential, destructive action, expense, or product decision. Do not commit, push, deploy publicly, change billing, or delete existing data without separate authorization.

Keep React/Vite/Tailwind and FastAPI unless a specific blocker justifies a small change. Do not rewrite in Next.js, introduce microservices, add a new AI provider, or build a new admin portal. Focused dependencies needed for reliable uploads, persistence, security, and tests are acceptable; explain and pin them. Keep unfinished extras hidden. Do not expand into payments, barcode catalogs, social features, or a browser extension.

## 2. Audit these concrete problems first

Verify these against the current checkout and running process; do not assume a prior chat proves they are fixed:

- frontend/src/App.jsx combines almost the entire UI, exposes /database and DatabasePage, and displays provider, rule-engine, and backend-startup messages to shoppers.
- backend/app/core/gemini.py currently collapses provider exceptions into None. The REST helper has no bounded retry policy. Full-list validation can discard useful output because an ingredient name differs, one item is missing, or alternatives do not number exactly three.
- backend/app/core/database.py records only successful scored results, silently ignores persistence failures, contains duplicated definitions, and returns global history. Cache records have weak freshness/version handling.
- backend/app/api/routes.py exposes /api/stats and /api/queries and performs OCR plus analysis before users review extracted text. Verify image/upload provenance and profile propagation.
- backend/app/main.py enables public Swagger; config loads .env relative to the working directory. Verify configuration resolution from each documented launch command without exposing secrets.
- Documentation says the score is rule-based, while scoring.py also has a gated NOVA-assisted path. Determine the actual contract; make results, tests, and documentation truthful and consistent.
- A populated key is not evidence of a successful provider request. An empty golden set is not evidence of validated accuracy. Verify actual results rather than repeating old handoff claims.

Capture a short baseline, then fix root causes, not just visible symptoms.

## 3. Remove implementation details from the customer experience

- Remove Database navigation, database explorer components/routes, SQL tables, schema displays, query-plan views, cache counters, debug toggles, and related public fetching. Direct /database navigation must not resurrect the explorer.
- Remove public access to /api/queries and internal /api/stats. Preserve SQL demonstrations as local scripts and docs. Do not replace them with an unauthenticated hidden admin route.
- Disable /docs, /redoc, and /openapi.json in production. Allow explicit local-development enablement only; do not link them from the app. Hiding documentation is not access control: protect the actual data endpoints.
- Remove customer copy such as "database fallback", "ML disabled", "missing GEMINI_API_KEY", "start the backend", stack traces, model IDs, latency, and internal reason codes.
- Show ordinary product language: "Check ingredients", "Ingredient details", "Things to consider", "Scan history". When recovery is needed, say what the person can do: "We couldn't read this photo. Try a clearer image or paste the ingredients."
- Do not hide meaningful uncertainty. Use concise copy such as "Some ingredients could not be assessed" or "This is a limited assessment." Never imply unknown ingredients are safe. Keep AI-generated labeling, evidence distinctions, a short methodology explanation, attribution, and the not-medical-advice disclaimer.
- Separate public response models from internal diagnostics. Customer APIs should return the result, completeness, lifecycle/save status, safe message codes, and opaque identifiers, not SQL, exception payloads, credentials, or infrastructure details.

## 4. Rebuild the UI in professional neo-brutalism

This is a coordinated design-system change, not random bright colors on the existing layout.

- Use a warm off-white background, near-black ink, bold 2-3 px borders, restrained 4-6 px hard offset shadows, small corner radii, strong sans-serif typography, generous spacing, and a limited lime/yellow/lavender accent palette. Define reusable tokens; no scattered hard-coded theme colors. Reserve concern colors for meaning.
- Keep it polished and readable: no glassmorphism, blurry shadows, excessive pills, giant empty cards, chaotic rotations, fake product imagery, or generic dashboard clutter. Bundle an appropriate font or use a reliable system stack; do not depend on a remote font to render correctly.
- Build reusable buttons, inputs, tabs, cards, badges, dialogs, alerts, skeletons, and empty states. Split the monolithic frontend into pages, components, API/services, and hooks without introducing unnecessary abstractions.
- Header: brand, Scan, History, and only working user-relevant settings. Prioritize the scan action. Keep advanced preferences unobtrusive.
- Scan: obvious Camera / Upload / Paste choices; practical framing guidance; preview, retake/remove, readable ingredient editor, and one clear primary action. Request camera access only after user action, not automatically on page load.
- Results: prominent assessment and score when justified, a brief interpretation, important ingredient concerns, expandable explanations, alternatives only when supported, and clear New scan / History / export actions where implemented. Explain that the score is an estimate, not a clinical measurement. Do not show an empty technical NOVA card.
- History: recognizable scan titles, date/time, assessment, input type, search, reopen, delete, clear-all confirmation, loading/error/empty states, and pagination. No global database statistics or developer metadata.
- Provide real loading states. Do not advance pretend backend stages on a timer. If progress is unavailable, use an honest indeterminate indicator. Preserve input on error, prevent duplicate submission, and ignore stale responses after navigation or a new scan.
- Verify at 360, 390, 768, 1280, and 1440 px, with keyboard navigation and 200% zoom. No horizontal overflow, clipped dialogs, overlapping score labels, or invisible focus. Target normal-text contrast of at least 4.5:1 and touch targets of approximately 44 px; use semantic controls, accessible names, focus management, and reduced-motion support.

## 5. Make Gemini-first behavior explicit and reliable

For every new valid ingredient-analysis submission, attempt live Gemini analysis before reading cached explanations as a fallback. Local parsing, safety validation, matching for scoring, and deterministic calculations may still run first; those are not cache-first enrichment. Do not reject a plausible unfamiliar food list solely because it lacks knowledge-base matches. Reading a saved result, refreshing history, and retrying an already-completed idempotent request must not trigger another paid analysis.

For image scans, Gemini first extracts the label. Then the user reviews/corrects the text and the confirmed list receives the same Gemini-first analysis as pasted text. A database cannot decode an unreadable image: if extraction fails, offer retake/upload/paste rather than inventing matches. Link extraction, confirmation, and analysis to one scan lifecycle. Record a later deliberate re-analysis as a linked revision, not an accidental duplicate.

Implement a provider service with typed outcomes rather than a catch-all None:

1. Verify the installed HTTP/SDK behavior and current official Gemini documentation. Confirm the configured model is actually available to this key/project and supports the required image and structured-output capabilities. Do not assume the existing default model ID is valid or silently switch providers. Correct a demonstrably invalid model setting with a documented compatible choice; do not change billing. Distinguish configuration presence from a successful live probe. Do not call the provider on every health check.
2. Reuse an appropriately managed HTTP client. Bound concurrency and avoid blocking the async event loop. Configure connect/read/pool timeouts and an overall deadline covering all retries and parsing. Prevent overlapping SDK and application retry loops.
3. Classify authentication/permission, invalid model, invalid request, rate limit, exhausted quota, transient server failure, connection failure, timeout, blocked output, no candidates, truncation, malformed JSON, and schema/completeness failures separately in private diagnostics.
4. Retry only eligible transient failures with exponential backoff and jitter, respecting Retry-After when supplied and the remaining deadline. Use a small configurable cap, such as at most three attempts total per operation. Do not retry permanent credential/schema/request errors or exhausted daily quota as though they are transient. Never use unbounded retries or multiple speculative model calls.
5. Set explicit request-level time budgets and align the frontend deadline above the backend budget. Reasonable starting budgets are 30 seconds for text analysis and 30 seconds for image extraction, with user review separating the operations; tune from measurements. Expire pending work predictably and prevent duplicate background work after timeout. Do not claim that client cancellation undoes a provider call.
6. Send the ingredient list as untrusted data, not instructions. Use structured output and local typed validation. Request stable ingredient token IDs so punctuation, aliases, and capitalization changes do not invalidate an otherwise useful response. Preserve order and duplicate-to-canonical mappings without double-counting score penalties.
7. Validate each ingredient independently: identity, allowed concern/unknown value, text types/lengths, and completeness. Keep valid entries. Retry or repair only when justified and within the same budget; then fill missing entries from suitable stored knowledge. Invalid optional alternatives must not invalidate every ingredient explanation. Aim for up to three useful alternatives, not three fabricated ones.
8. Track per-item provenance and analysis completeness. A partially AI-generated result with stored supplementation is mixed internally, not falsely all-Gemini. Unknown or missing assessment must remain unknown, never default to low risk. Reject unexpected extra ingredient IDs and content that cannot be safely associated with the label.
9. Fallback order after live failure: relevant verified knowledge, then suitable versioned cached generated summaries, then an explicit unknown/limited result. Use existing normalization, INS/E-code aliases, and validated fuzzy-match safeguards. Do not present cached AI text as human-verified.
10. Cache validated reusable information, with model/prompt/schema versions, timestamps, expiry/invalidation policy, and provenance. Never reuse condition-specific or product-specific statements as universal ingredient facts. Cache keys for contextual alternatives must include the context that affects them. A cache write failure must not discard a valid provider result or silently count as durable scan persistence.
11. If missing credentials or a deliberately implemented operational guard prevents a live attempt, record that precise reason privately. Do not add a normal cache-first optimization or silently skip Gemini on healthy requests. Backpressure/rate limits must be explicit and bounded.

Keep the numeric score separate from generated prose. Preserve tested scoring constants, safety caps, deduplication, and the existing validated NOVA gate; do not turn Gemini into an unconstrained health-score generator. Reconcile the rule-only versus NOVA-assisted documentation conflict against the intended tested contract and clearly record the decision. Never label an ML-influenced score as purely rule-based, bypass the model self-test, or claim a model is ready when dependencies/artifacts are missing. Gemini identification must not masquerade as a verified knowledge-base match or artificially increase scoring coverage. If there is insufficient evidence to justify an assessment, show that state rather than a reassuring high score caused by unmatched ingredients contributing no penalties; define and test the presentation gate without silently rewriting scoring constants.

## 6. Persist every accepted scan lifecycle, not just successes

Use durable backend storage as the source of truth. sessionStorage/localStorage may cache UI state but must not be the only history.

Choose the least risky database suited to the actual delivery environment. Existing SQLite may remain for a single-node workload if transactions, concurrency, backup, and restart tests pass. Use PostgreSQL when the target deployment or measured concurrency requires it; prefer it over introducing an unrelated MongoDB stack. Do not force an infrastructure migration merely to look professional, and do not build two independent persistence implementations unnecessarily. Document the decision. If migrating, back up first, preserve existing records, provide a repeatable migration/import, verify counts and relationships, and document rollback. Never reset the database to get tests passing.

Implement an explicit lifecycle such as received -> extracting -> awaiting_confirmation -> analyzing -> completed/completed_limited/failed/cancelled/interrupted. Define legal transitions. Persist an accepted attempt before expensive provider work, and atomically save its final result and ingredient children. Invalid/no-food/no-text outcomes and provider failures must be represented when they reach the scan service; malformed or abusive requests need only bounded sanitized validation telemetry. Browser-side failures that never reach the server cannot honestly be claimed as server-persisted scans.

Required data, using normalized tables and a versioned result snapshot where appropriate:

- Opaque public scan ID, owner/session scope, request/correlation ID, and unique owner-scoped idempotency key.
- UTC created/updated/completed times; source camera/upload/paste; status; linked parent/revision; result schema and scoring/knowledge versions.
- Parsed ingredient names, order, normalized identity, match/assessment state, concern/unknown state, and per-item provenance needed to reopen the result accurately.
- Final assessment/score when valid, completeness, alternatives, and the structured snapshot. No fabricated score for a failed scan.
- Separate provider-attempt records with operation, attempted/skipped state, attempt number, model, sanitized outcome/status, duration, fallback category, and usage when actually available. Do not store keys, raw headers, full prompts, images, or raw provider bodies.

Additional requirements:

- Use migrations with a schema version, constraints, foreign keys, appropriate indexes, transactional writes, and idempotent seeds. Handle cache updates deliberately rather than preserving the first generated record forever.
- One logical submission must produce one stored scan despite double-clicks, frontend retries, concurrent identical requests with the same key, or a lost HTTP response. Enforce uniqueness in the database. Reuse a completed result; reject a reused key with different input. Distinct intentional scans receive distinct IDs. Do not promise exactly-once provider billing across crashes.
- Do not hold a write transaction open while waiting for Gemini. Reconcile abandoned processing records after restart instead of leaving them pending forever. Cancellation must not overwrite a completed result.
- If the initial durable write fails, do not start expensive analysis and pretend the scan was accepted. If final persistence fails, do not show "saved" or claim completion persisted. Return a safe retryable product state, retain the durable attempt, and support recovery with the same idempotency key. No silent swallowed persistence errors.
- Persisted history must survive backend restart and load results by stable ID, including direct navigation and browser refresh. Merely reopening or exporting a result must not re-run Gemini or create another scan.
- Add paginated search/list/detail and scoped delete/clear APIs. Make deletion transactional and reflected after refresh; do not merely remove a local UI row. Keep history state and lifecycle state consistent.

## 7. Privacy, ownership, and application security

- Global scan history is unacceptable. Reuse existing authentication if present. Otherwise use a cryptographically random, server-issued anonymous session with an HttpOnly cookie, SameSite protection, and Secure in production. Scope list/detail/update/delete/export/idempotency operations on the server. An arbitrary client-supplied owner ID or hard-to-guess scan ID alone is not authorization.
- Without accounts, describe history honestly as belonging to this browser/session, not cross-device sync. Explain the consequence of clearing site cookies. Do not build an unnecessary login system just for this repair.
- Preserve legacy unowned scans privately during migration; do not expose them to all visitors or assign them automatically to the next visitor. Document an owner-only local recovery/import procedure.
- If cookies are used across frontend/API origins, configure credentialed requests and explicit CORS origins consistently. Add appropriate CSRF/origin defenses to mutations. Never combine credentialed access with a wildcard origin.
- Keep Gemini keys and database credentials server-side and out of VITE variables, bundles, git, logs, screenshots, and reports. Do not ask me to paste keys into chat. If a key is discovered in tracked/public files, identify the exposure without reproducing it and tell me to rotate it.
- Minimize stored user data. Store parsed ingredient names and the sanitized result needed for history, but not image bytes, EXIF, full raw labels, prompts, or provider bodies by default. Sanitize recursively: removing only detected_text while retaining raw copies elsewhere is not redaction. Be honest that ingredient names are retained and may reveal much of a label.
- If retaining original text or images becomes necessary, implement explicit opt-in and retention/deletion behavior first. Avoid retaining health-condition profiles in telemetry; use only the minimum needed for an explicitly selected feature. Do not silently send profiles to external providers or reuse scans for training.
- Provide a concise privacy notice describing AI processing, saved history, anonymous ownership, and deletion. Define a configurable retention period and cleanup command; document backups and deletion limitations. Do not call scans anonymous if an identifier still links them to a browser or account.
- Validate supported file signatures and decoded image dimensions, not just image/* MIME or filename. Cap file bytes, multipart overhead, pixel count, and request size; reject corrupted, animated/unsupported, or decompression-bomb inputs safely. Do not fetch user-supplied image URLs. Keep uploads in memory where practical and release resources.
- Parameterize queries. Treat user and model text as plain text, not HTML. Validate any evidence links. Add appropriate rate/request/concurrency limits without allowing an attacker to fill the database with unbounded failed attempts.
- Use sanitized error mapping and non-sensitive request IDs. Public liveness/readiness should be minimal; detailed provider/database/model diagnostics belong in protected/local operational tools. Health requests must not generate paid analyses.

## 8. Complete the actual user flows

- Camera: handle permission denial, unavailable devices, insecure context, capture readiness, retake, switching input mode, and navigation. Stop media tracks and revoke object URLs correctly.
- Upload: validate before decoding where possible, preserve orientation, resize without destroying small-label readability, offer preview/remove, and report unsupported formats without exposing internals. Maintain distinct camera/upload provenance through later text correction.
- OCR: never invent obscured words. Show extracted ingredients for review before scoring; preserve uncertainty. Empty/no-label/blurred images get actionable recovery. Correcting text must not lose the originating scan ID or create an extra completed scan unintentionally.
- Paste: support typing and manual paste when clipboard permission fails. Validate empty, whitespace-only, too-short, overly long, non-food, nested ingredients, INS/E codes, and duplicates consistently across client and server.
- Results: distinguish unknown concern from low concern; missing data from zero; AI notes from verified evidence; and processing classification from nutritional assessment. Do not infer quantities, nutrient totals, allergies, diagnoses, disease outcomes, or guaranteed safety from an ingredient list. Avoid claiming a recommended alternative is safe for a user's condition or allergy.
- Never fabricate citations or promote generated/cached text to verified evidence automatically. Keep explanations cautious and grounded; withhold unsupported health claims. Do not render a provider's low/medium/high label as a clinical risk probability, and do not invent product brands, nutrient values, or individualized safe-consumption frequencies.
- Preserve existing tested personalization if available, carry it consistently through image/text/re-analysis paths, and label its limits. Do not invent an unvalidated medical recommendation feature. Hide unsupported settings instead of accepting and silently ignoring them.
- History: correct UTC storage and local display, including the expected Asia/Kolkata display for the demo; no double timezone conversion. Reopening should reproduce the saved assessment/version rather than silently re-score it.
- Refresh/deep links/back/forward: restore durable results by ID; show a proper missing/deleted/unauthorized state, not a crash or a previous user's result. Handle corrupted browser storage and disabled storage gracefully.
- Preserve and repair report/PDF export if it exists. It must use the authorized saved result, render printable text without clipping, and omit SQL/provider diagnostics. Do not ship a dead Export button; explicitly flag any required core feature that remains missing rather than disguising it as complete.

## 9. Tests and release gates are mandatory

First run the existing tests/build and record the baseline. Add deterministic tests using mocked provider transport and isolated temporary databases; ordinary tests must not spend Gemini quota, download model artifacts, or touch my real history. Use the repository's real commands. Add and document frontend unit/component and end-to-end test commands if absent; a Vite build alone is not a UI test.

Test at least these scenarios:

**Gemini and analysis**
- Complete successful response; live-first behavior despite a populated cache; saved-result reopen without provider calls.
- Transient 503 or connection failure followed by success; persistent failure; eligible 429 with bounded Retry-After; exhausted quota; non-retryable credential/request/model failures; deadline exhaustion and concurrency limit.
- Missing candidates, blocked output, truncated output, malformed JSON, wrong types, nulls, missing/extra IDs, duplicate tokens, normalized name variations, and missing alternatives.
- Partial valid responses retained; only missing entries supplemented; complete failure uses stored knowledge; no matching knowledge remains unknown, not low concern.
- No secrets/raw payloads leak through HTTP responses, telemetry, snapshots, or logs. Score constants, safety caps, deduplication, profile effects, and NOVA gate behavior remain covered.

**Persistence and isolation**
- Successful, limited, failed, and interrupted attempts; transaction rollback; final-write failure; restart recovery; concurrent submissions; unique idempotency enforcement; same key/different payload rejected.
- History survives restart; search/pagination stable; direct result retrieval; delete/clear persisted; cache and scan storage failures treated separately.
- Two independent browser sessions cannot list, open, modify, delete, export, or poll each other's scans. Include guessed IDs and idempotency keys. Verify cookie/CORS/CSRF behavior in the real browser.
- Fresh schema install and upgrade from a copy of the existing database, migration rerun safety, legacy ownership handling, backup and restore. If PostgreSQL is selected, actually test it; SQLite-only tests are not proof of PostgreSQL compatibility.

**Frontend/end-to-end**
- Paste -> analyze -> results -> history -> reopen -> refresh -> delete.
- Image upload -> extraction -> review/edit -> analysis -> history, with one linked lifecycle.
- Permission denied/no camera, corrupted/oversized upload, empty/non-food text, backend unavailable, provider slow/failing, unknown ingredients, no alternatives, stale responses, double-click, cancel, and expired session.
- Customer routes contain no database/SQL/schema/debug/provider-error panels. Production API docs/internal endpoints are inaccessible even through direct requests. All visible actions work.
- Real layout checks at the stated widths, keyboard-only operation, focus handling, readable contrast, and reduced-motion behavior. Capture genuine screenshots of Scan, Results, and History, including useful empty/loading/error states. Check console and failed network requests.

After deterministic tests pass, perform a bounded live smoke test using the already-configured key if available: at most three scan workflows and ten provider requests including retries, using non-sensitive generic fixtures. Include one text and one real readable label-image path if a suitable fixture exists. Do not use screenshots of the app UI as label-OCR success evidence. Record actual provider success/fallback, elapsed time, model identity, and durable scan IDs without dumping private data. A mocked pass or "key configured" is not a live pass. If credentials/network/quota prevent this, mark live verification BLOCKED, explain the exact owner action, and do not claim the integration is fully verified.

Measure latency and fallback reasons, including whether each fallback was provider failure, local validation failure, or configuration failure. Do not invent reliability percentages from a tiny smoke test. Empty golden data means accuracy evaluation is NOT PERFORMED, not passed. Never fabricate branded product labels or health benchmarks.

## 10. Operational readiness and handoff

- Provide one reproducible Windows development startup path and a documented production-build/start path. Resolve paths independently of the current working directory; use placeholders in .env.example. Verify the documented commands.
- Document required environment settings, safe defaults, storage location, migrations, backup/restore, retention, allowed origins, provider model/timeouts/retry limits, session settings, and production docs/debug disabling. Do not write secrets into docs.
- Keep optional ML startup/download failures from disabling text analysis or the app. Do not bypass the model readiness gate or hide a failed self-test in the handoff.
- Audit dependencies and fix relevant issues without blind major upgrades or force flags. Freeze compatible versions and report remaining material advisories honestly.
- Record private operational events with correlation IDs: provider outcome category, attempt count, duration, completion/fallback counts, and persistence failures. Keep request labels, profiles, credentials, and raw provider responses out of logs. This is not another customer analytics dashboard.
- Update existing README, architecture, PRD deviations, DATABASE, decisions, and HANDOFF docs to match what actually ships. Retain ER diagrams, table definitions, relationships, indexes, transaction boundaries, migration rationale, and parameterized SQL examples for my professor in these documents/local scripts only. Use synthetic documentation examples, not actual scan records.

Work in this order: baseline and data protection; shared contracts/lifecycle; provider reliability and persistence/isolation; scan/results/history flow and neo-brutalist UI; integration/security/browser tests; docs and final handoff. Independent implementation may be parallelized after agreeing on contracts, but integration must be verified centrally. Do not stop at a visual reskin or claim completion while persistence, ownership, or real-provider verification is untested.

Your final response must contain:
1. What changed, grouped by frontend/backend/database/security.
2. Confirmed causes of the Gemini failures and corresponding fixes; separate proven findings from hypotheses and remaining upstream limitations.
3. Database choice, migration/data preservation status, and scan lifecycle/idempotency behavior.
4. Exact setup/run/test commands and actual pass/fail/skip counts; mocked versus live checks clearly separated.
5. Screenshot/evidence paths and a short reproducible user-flow walkthrough.
6. Any blocking gaps and the smallest concrete action I must take.

No claim of zero bugs, guaranteed provider uptime, validated medical safety, or production readiness without evidence. Deliver the strongest verified working application possible within this scope, and make any remaining uncertainty explicit to me in the handoff rather than exposing developer failures to shoppers.
