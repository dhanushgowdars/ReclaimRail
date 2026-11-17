# ReclaimRail acceptance matrix

This matrix is the only current completion ledger. Older phase documents remain useful
design history but cannot override these statuses.

## Phase status

| Phase | Scope | Current status | Exit evidence still required |
| --- | --- | --- | --- |
| 1 | Architecture and bounded-agent thesis | VERIFIED | keep diagrams/contracts aligned with runtime |
| 2 | Foundation, PostgreSQL, Redis, CI | VERIFIED | fresh Windows/Docker migration, backend and frontend gates passed in Gate 1 |
| 3 | Signed webhook ingestion | VERIFIED | controlled locally signed acceptance/idempotency passed; provider-emitted Test Mode evidence remains required |
| 4 | Payment state machine | VERIFIED | fresh signed failure projected once from `unknown` to `failed` |
| 5 | Incident detection | VERIFIED | current DB integration rerun |
| 6 | Bounded recovery agent | PARTIAL | current provider-backed acceptance bundle and AI/fallback labeling |
| 7 | Outcome reconciliation | PARTIAL | current live Test Mode recovery/pending/reversal evidence |
| 8 | Merchant command center | PARTIAL | browser/empty/error/live-state evidence |
| 9 | Frontend redesign and Payment Lab | PARTIAL | visual, accessibility and E2E gates |
| 10 | Judge experience rebuild | PARTIAL | five-minute recorded path and truthful failure demonstration |
| 11 | Control-plane hardening | BROKEN | dependency vulnerabilities and public read API access must be resolved for deployment |
| 12 | Evidence-first guided/continuous live command | PARTIAL | current end-to-end provider replay and browser evidence |
| 13 | Operations navigation/Recovery Brain | PARTIAL | commit local trace UI; E2E evidence for every judge-relevant state |
| 14 | Safety invariants and contracts | VERIFIED | reconcile obsolete contract text |
| 15 | Versioned payment truth | VERIFIED | committed baseline is verified; fresh migration/integration gate required on the approved branch |
| 16 | Reliable events/reconciliation | BROKEN | `G1-P0-001`: unavailable provider reads loop across polls and amplify evidence/truth versions |
| 17A | Gemini investigator core in shadow mode | PARTIAL | current local work must be preserved and rerun against PostgreSQL |
| 17B | Live investigator closure | BROKEN | locked benchmark thresholds and final repository gates |
| 18 | Claim validation and action ranking | NOT IMPLEMENTED | all P18 gates |
| 19 | Policy and state-bound approval | NOT IMPLEMENTED | all P19 gates; reuse older approval only where it satisfies the new contract |
| 20 | Durable provider execution | NOT IMPLEMENTED | all P20 gates; reuse older executor only where it satisfies the new contract |
| 21 | Security, resilience and receipts | NOT IMPLEMENTED | all P21 gates plus dependency/access remediation |
| 22 | Investigation Room | NOT IMPLEMENTED | all P22 gates; existing case page is a precursor |
| 23 | Scenario Lab, measured evaluation and submission | NOT IMPLEMENTED | all P23 gates, public demo and video |

## Current release blockers

| ID | Requirement | Status | Acceptance gate |
| --- | --- | --- | --- |
| BASE-01 | Preserve Phase 17B staged/unstaged/untracked work | VERIFIED | separate staged/unstaged/combined patches, exact file copies and Git bundle exist; original worktree is frozen; approved clean continuation branch has zero application changes |
| BASE-02 | Review sanitized-out `.env.example` change | VERIFIED | six investigator settings passed local type/range/order checks; secret-pattern count was zero; no value was exposed |
| BASE-03 | Current PostgreSQL migration chain | VERIFIED | clean Gate 1 database upgraded base-to-`e7a1c2d3f417`; `current`, `heads` and `check` passed |
| BASE-04 | Current complete backend suite | VERIFIED | `686 passed, 1 skipped`; skip is individually recorded and no test failed |
| BASE-05 | Frontend compile/lint | VERIFIED | already passed on snapshot; rerun after any dependency change |
| BASE-06 | Frontend security audit | BROKEN | zero unaccepted critical/high findings |
| BASE-07 | Backend security audit | BROKEN | zero unaccepted known runtime findings |
| BASE-08 | Browser behavior and accessibility | NOT IMPLEMENTED | approved E2E plus 1024/1440/1920, keyboard and contrast evidence |
| BASE-09 | Documentation consistency | BROKEN | README/contracts/statuses match current code and evidence |
| BASE-10 | Owner-only default-branch identity | VERIFIED | future commits repeat the same verification |
| BASE-11 | Full local controller health | VERIFIED | API ready, 11 processes started and 8/8 workers initially healthy |
| BASE-12 | Signed webhook idempotency/projection | VERIFIED | `202 accepted`, `200 duplicate`, one canonical event, one applied failed transition |
| BASE-13 | Provider-truthful persisted case visible in frontend | BROKEN | synthetic identifiers triggered provider unavailability; case creation refused and no case page could be proven |
| BASE-14 | Bounded provider-read reconciliation | BROKEN | 453/453 batches unavailable; cross-batch cooldown/circuit/evidence idempotency gate failed |

## Gate 1 baseline reproduction

| ID | Requirement | Current status | Evidence / remaining gate |
| --- | --- | --- | --- |
| G1-01 | Clean isolated Windows/Docker runtime | VERIFIED | isolated Compose project; healthy PostgreSQL/Redis; original project resources preserved |
| G1-02 | Base-to-head migrations and schema drift check | VERIFIED | head `e7a1c2d3f417`; no new upgrade operations detected |
| G1-03 | Backend deterministic quality gate | VERIFIED | format, lint, strict mypy and `686 passed, 1 skipped` |
| G1-04 | Frontend compile gate | VERIFIED | ESLint and production build passed |
| G1-05 | Full controller startup | VERIFIED | ready API/web and 8/8 healthy workers |
| G1-06 | Signed webhook stored/projected exactly once | VERIFIED | one canonical event, delivery count two, one applied transition |
| G1-07 | Provider-emitted Test Mode provenance | PARTIAL | tested payload was controlled synthetic and locally signed |
| G1-08 | Bounded reconciliation under provider unavailability | BROKEN | `G1-P0-001`; 453 unavailable batches and unbounded new evidence |
| G1-09 | Same persisted recovery case visible in frontend | BROKEN | deterministic truth gate correctly refused an ineligible case |
| G1-10 | No live Gemini corpus | VERIFIED | Gemini shadow disabled; no live call |
| G1-11 | No provider mutation or money movement | VERIFIED | no case/action/approval/outcome; only repeated read verification occurred |
| G1-12 | Repository remains unchanged by reproduction | VERIFIED | tracked worktree remained clean; no application file changed |

Gate 1 decision: `BROKEN`. Gate 2 and feature implementation remain blocked until the
owner approves and closes the dedicated `G1-P0-001` remediation gate below.

## Gate 1A P0 remediation acceptance

| ID | Required fix behavior | Status | Acceptance gate |
| --- | --- | --- | --- |
| G1A-01 | Enforce cooldown/backoff for unavailable and manual-investigation states | NOT IMPLEMENTED | repeated polls inside the cooldown make zero provider calls |
| G1A-02 | Make equivalent provider-unavailable evidence idempotent within its retry window | NOT IMPLEMENTED | repeated identical failure produces no additional evidence row or truth version |
| G1A-03 | Persist a retry budget/circuit state across worker batches | NOT IMPLEMENTED | budget survives loop iterations/restart and opens visibly at the configured threshold |
| G1A-04 | Keep deterministic fail-safe truth behavior | NOT IMPLEMENTED | unavailable evidence still produces manual investigation without enabling recovery |
| G1A-05 | Separate controlled synthetic inputs from live provider adapters | NOT IMPLEMENTED | synthetic IDs cannot reach Razorpay; tests use a deterministic provider stub |
| G1A-06 | Prove recovery after provider availability returns | NOT IMPLEMENTED | fresh matching provider evidence resolves truth without stale unavailable evidence dominating |
| G1A-07 | Add negative/race/regression coverage | NOT IMPLEMENTED | focused tests cover polling, concurrent workers, restart and evidence uniqueness |
| G1A-08 | Re-run complete Gate 1 on a fresh database | NOT IMPLEMENTED | all G1 gates pass, including same-case frontend evidence |

## Phase 17B acceptance

| ID | Requirement | Current status | Gate |
| --- | --- | --- | --- |
| P17B-01 | Preserve and isolate the current benchmark/runtime changes | PARTIAL | reviewable commits/patches on an approved branch |
| P17B-02 | Supported non-duplicate model route | BROKEN | no deprecated alias pretending to be independent failover |
| P17B-03 | Structured-output contract passes deterministic fixtures | VERIFIED | current focused tests pass |
| P17B-04 | Bounded provider retry and sanitized diagnostics | VERIFIED | focused retry/failover/quota tests pass; no live-provider claim is implied |
| P17B-05 | Frozen corpus remains unchanged during diagnosis | VERIFIED | corpus hash recorded before live run |
| P17B-06 | Provider access/quota preflight | NOT IMPLEMENTED | one cheap diagnostic establishes model access before corpus |
| P17B-07 | Truth-compatible rate | BROKEN | at least 80% on a complete corpus run |
| P17B-08 | Required-tool selection | BROKEN | at least 80% |
| P17B-09 | Citation validity | BROKEN | 100% |
| P17B-10 | Abstention accuracy | BROKEN | at least 80% |
| P17B-11 | Provider and malformed-output selection gate | BROKEN | both 0% for the selected report |
| P17B-12 | Runtime remains advisory/shadow | VERIFIED | no mutation tool; deterministic pipeline unaffected |
| P17B-13 | Frontend labels incomplete/fallback/abstained truthfully | PARTIAL | committed UI plus browser evidence |
| P17B-14 | Final DB, backend, frontend and security gates | PARTIAL | all baseline gates pass on the committed branch |

## Remaining-phase gate summary

Detailed requirements remain in `MASTER-EXECUTION-PLAN.md`. These are the mandatory
reviewer-visible outcomes that may not be removed.

| Phase | Mandatory outcome gates |
| --- | --- |
| 18 | validate every AI claim against case-owned evidence; reject unsupported/cross-case/future citations; generate feasible coordinate-free intents; compare safe alternatives economically; expose rejected claims and ranking inputs in the frontend |
| 19 | bind policy and approval to case/truth/action/evidence versions; expire/supersede stale approvals atomically; prove non-overridable hard stops; make approve/reject/expired effects visible |
| 20 | commit durable intent before provider mutation; deterministic idempotency and concurrency control; classify ambiguity as in-flight/reconciliation-required; reconcile before retry; expose every attempt and provider proof |
| 21 | remediate dependencies and access control; validate tenant/case ownership; redact secrets/PII; add abuse/rate limits; generate tamper-evident receipt binding truth through outcome; prove restart/recovery behavior |
| 22 | one reviewer workflow for objective, truth, tool transcript, hypotheses, claims, alternatives, policy, approval, execution and outcome; truthful empty/error/fallback/abstention states; keyboard and viewport gates |
| 23 | reproducible cohort with treatment/control or paired baseline, denominators, exception list and confidence; separate synthetic/Test Mode/production; five-minute demo, public README/video, clean clone setup and final evidence bundle |

## Required phase completion record

Copy this table into `WORK-LOG.md` for every phase:

| Field | Required value |
| --- | --- |
| Phase and requirement IDs | exact IDs |
| Baseline branch/commit | full commit |
| Changed files | complete list |
| Commands | exact commands, using PowerShell for owner-run steps |
| Backend result | pass/fail/skip counts and environment |
| Migration result | upgrade/check and database provenance |
| Frontend result | lint/build/E2E plus route/viewports |
| Security result | npm and Python audit findings/dispositions |
| Provider result | not run, or bounded sanitized evidence |
| Frontend evidence | screenshots/video/API-to-UI mapping |
| Limitations | explicit unresolved items |
| Git identity | author and committer |
| Decision | owner approved/rejected/deferred |
