# ReclaimRail acceptance matrix

This matrix is the only current completion ledger. Older phase documents remain useful
design history but cannot override these statuses.

## Phase status

| Phase | Scope | Current status | Exit evidence still required |
| --- | --- | --- | --- |
| 1 | Architecture and bounded-agent thesis | VERIFIED | keep diagrams/contracts aligned with runtime |
| 2 | Foundation, PostgreSQL, Redis, CI | VERIFIED | committed baseline is verified; fresh current-branch PostgreSQL and CI gate still required |
| 3 | Signed webhook ingestion | VERIFIED | current DB integration rerun |
| 4 | Payment state machine | VERIFIED | current DB integration rerun |
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
| 16 | Reliable events/reconciliation | VERIFIED | committed baseline is verified; fresh migration/integration gate required on the approved branch |
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
| BASE-03 | Current PostgreSQL migration chain | PARTIAL | `alembic upgrade head` and `alembic check` pass on a clean database |
| BASE-04 | Current complete backend suite | PARTIAL | zero failures; skips individually explained |
| BASE-05 | Frontend compile/lint | VERIFIED | already passed on snapshot; rerun after any dependency change |
| BASE-06 | Frontend security audit | BROKEN | zero unaccepted critical/high findings |
| BASE-07 | Backend security audit | BROKEN | zero unaccepted known runtime findings |
| BASE-08 | Browser behavior and accessibility | NOT IMPLEMENTED | approved E2E plus 1024/1440/1920, keyboard and contrast evidence |
| BASE-09 | Documentation consistency | BROKEN | README/contracts/statuses match current code and evidence |
| BASE-10 | Owner-only default-branch identity | VERIFIED | future commits repeat the same verification |

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
