# ReclaimRail acceptance matrix

The complete F-01–F-50 catalogue and established Gate 1A → Gate 2 → Phase 17B →
Phases 18–23 order were owner-approved and locked on 18 November 2026. Status rows still
change only from repository evidence; roadmap approval is not feature-completion evidence.

This matrix is the only current completion ledger. Older phase documents remain useful
design history but cannot override these statuses.

`NEEDS INSPECTION` is permitted when current evidence is insufficient to choose another
classification safely. It is temporary and never means complete.

## Phase status

| Phase | Scope | Current status | Exit evidence still required |
| --- | --- | --- | --- |
| 1 | Architecture and bounded-agent thesis | VERIFIED | keep diagrams/contracts aligned with runtime |
| 2 | Foundation, PostgreSQL, Redis, CI | VERIFIED | fresh Windows/Docker migration, backend and frontend gates passed in Gate 1 |
| 3 | Signed webhook ingestion | VERIFIED | controlled locally signed acceptance/idempotency passed; provider-emitted Test Mode evidence remains required |
| 4 | Payment state machine | VERIFIED | fresh signed failure projected once from `unknown` to `failed` |
| 5 | Incident detection | VERIFIED | Gate 2 Windows/PostgreSQL integration rerun passed |
| 6 | Bounded recovery agent | PARTIAL | current provider-backed acceptance bundle and AI/fallback labeling |
| 7 | Outcome reconciliation | PARTIAL | current live Test Mode recovery/pending/reversal evidence |
| 8 | Merchant command center | PARTIAL | browser/empty/error/live-state evidence |
| 9 | Frontend redesign and Payment Lab | PARTIAL | visual, accessibility and E2E gates |
| 10 | Judge experience rebuild | PARTIAL | five-minute recorded path and truthful failure demonstration |
| 11 | Control-plane hardening | PARTIAL | Gate 2 technical acceptance passes; production tenant identity, durable/distributed abuse control and hosted security evidence remain later gates |
| 12 | Evidence-first guided/continuous live command | PARTIAL | current end-to-end provider replay and browser evidence |
| 13 | Operations navigation/Recovery Brain | PARTIAL | commit local trace UI; E2E evidence for every judge-relevant state |
| 14 | Safety invariants and contracts | VERIFIED | reconcile obsolete contract text |
| 15 | Versioned payment truth | VERIFIED | committed baseline plus Gate 2 fresh migration/integration gate passed |
| 16 | Reliable events/reconciliation | VERIFIED | Gate 1A closes `G1-P0-001` with deterministic, full-controller, responsive and committed evidence; later provider-backed provenance remains mapped separately |
| 17A | Gemini investigator core in shadow mode | PARTIAL | current local work must be preserved and rerun against PostgreSQL |
| 17B | Live investigator closure | PARTIAL | implementation/canary/offline/PostgreSQL evidence remains valid; live model selection is unavailable after two incomplete governed attempts and remains a release/submission blocker |
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
| BASE-04 | Current complete backend suite | VERIFIED | Gate 2 exact candidate: `721 passed, 1 skipped`; skip is retained and no test failed |
| BASE-05 | Frontend compile/lint | VERIFIED | Gate 2 Next.js 16.4.6 candidate passes ESLint and production build |
| BASE-06 | Frontend security audit | VERIFIED | npm production audit is zero; `DEC-029` conditionally accepts the single dev-only `picomatch` advisory chain until a compatible upstream fix and requires reassessment before hosted/public deployment or Phase 21 closure |
| BASE-07 | Backend security audit | VERIFIED | `pip-audit` reports zero known findings for runtime and complete locked Python dependency sets |
| BASE-08 | Browser behavior and accessibility | PARTIAL | inspected 1024/1440/1920 Gate 1A views are legible; keyboard, contrast and automated E2E proof remain later gates |
| BASE-09 | Documentation consistency | BROKEN | README/contracts/statuses match current code and evidence |
| BASE-10 | Owner-only default-branch identity | VERIFIED | future commits repeat the same verification |
| BASE-11 | Full local controller health | VERIFIED | API ready, 11 processes started and 8/8 workers initially healthy |
| BASE-12 | Signed webhook idempotency/projection | VERIFIED | `202 accepted`, `200 duplicate`, one canonical event, one applied failed transition |
| BASE-13 | Provider-truthful persisted case visible in frontend | PARTIAL | controlled deterministic provider-stub case is fully legible; provider-emitted Test Mode provenance remains a separate provider-journey gate |
| BASE-14 | Bounded provider-read reconciliation | VERIFIED | durable cooldown, budget/circuit, restart containment, evidence idempotency and visible worker metrics passed |

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
| G1-08 | Bounded reconciliation under provider unavailability | VERIFIED | Gate 1A persisted controls prevent repeat calls/evidence growth and survive restart |
| G1-09 | Same persisted recovery case visible in frontend | PARTIAL | controlled provider-stub case legibly renders failed/eligible truth; provider-emitted provenance remains absent |
| G1-10 | No live Gemini corpus | VERIFIED | Gemini shadow disabled; no live call |
| G1-11 | No provider mutation or money movement | VERIFIED | no case/action/approval/outcome; only repeated read verification occurred |
| G1-12 | Repository remains unchanged by reproduction | VERIFIED | tracked worktree remained clean; no application file changed |

Gate 1 decision after Gate 1A: `VERIFIED` for the bounded-reconciliation acceptance scope.
`G1-P0-001`, full-controller reproduction, responsive frontend proof and the local closure
commit pass. Provider-emitted Test Mode provenance remains a separate provider-journey
requirement and is not falsely promoted by this decision.

## Gate 1A P0 remediation acceptance

| ID | Required fix behavior | Status | Acceptance gate |
| --- | --- | --- | --- |
| G1A-01 | Enforce cooldown/backoff for unavailable and manual-investigation states | VERIFIED | repeated polls inside cooldown made zero provider calls |
| G1A-02 | Make equivalent provider-unavailable evidence idempotent within its retry window | VERIFIED | blocked repeat left evidence/truth counts unchanged at 3/3 |
| G1A-03 | Persist a retry budget/circuit state across worker batches | VERIFIED | three scheduled reads opened the circuit; restart made zero unexpected calls; UI/health exposed state |
| G1A-04 | Keep deterministic fail-safe truth behavior | VERIFIED | unavailable evidence produced manual investigation without recovery eligibility |
| G1A-05 | Separate controlled synthetic inputs from live provider adapters | VERIFIED | synthetic control recorded one block and zero provider calls |
| G1A-06 | Prove recovery after provider availability returns | VERIFIED | expired unavailable evidence was superseded by fresh provider-stub failed truth; eligibility restored |
| G1A-07 | Add negative/race/regression coverage | VERIFIED | focused suite `22 passed`; complete backend suite `698 passed, 1 skipped` |
| G1A-08 | Re-run complete Gate 1 on a fresh database | VERIFIED | fresh migration, focused/full tests, lint/build/diff validation, complete 11-process controller with 8/8 workers, restart containment, and manually inspected 1024/1440/1920 plus populated-case evidence passed on the exact 22-path tree; provider-emitted provenance remains separate |

Gate 1A decision: `VERIFIED`. G1A-01 through G1A-08 pass and the owner-authorized local
23-path closure commit records the implementation and evidence. No push is part of this
decision.

## Gate 2 dependency and access-control acceptance

| ID | Requirement | Status | Evidence / remaining gate |
| --- | --- | --- | --- |
| G2-01 | Supported locked runtime dependencies | VERIFIED | Next.js/eslint-config-next 16.4.6, sharp 0.35.5, source-map-js 1.2.2 and patched Python transitive versions are locked; clean installs, lint and build pass |
| G2-02 | Zero known Python runtime findings | VERIFIED | runtime and complete locked exports each pass `pip-audit` with zero known vulnerabilities |
| G2-03 | Zero known npm production findings | VERIFIED | `npm audit --omit=dev --audit-level=high` reports zero vulnerabilities |
| G2-04 | Complete npm audit disposition | VERIFIED | `DEC-029` records bounded acceptance of the single lint/build-only `picomatch` advisory chain; npm production is clean, no forced breaking downgrade was used, and reassessment is mandatory before hosted/public deployment or Phase 21 closure |
| G2-05 | Protected operational backend reads | VERIFIED | 10 dashboard/case/incident/outcome/evaluation/worker/queue routes fail closed behind a constant-time server token; 52 focused tests pass |
| G2-06 | Public probe boundary | VERIFIED | `/health/live` and `/health/ready` remain public; worker and queue details require reviewer access |
| G2-07 | Browser reviewer session | VERIFIED | code exchanged once for signed expiring HttpOnly/SameSite=Strict cookie; code removed from browser storage and request headers; denied/authenticated/logout HTTP and inspected browser paths pass |
| G2-08 | Mutation defense in depth | VERIFIED | Payment Lab and approval proxies require signed session plus same-origin; existing lab/operator backend tokens remain server-only |
| G2-09 | Abuse and secret controls | VERIFIED | the approved controlled single-merchant scope has bounded per-client/global login throttles, request-size cap, server-only secrets and secret-shaped scan; durable/distributed throttle and hosted-proxy validation remain explicitly mapped to deployment/Phase 21, not hidden Gate 2 claims |
| G2-10 | Complete regression and Windows runtime | VERIFIED | Windows validation passed three PostgreSQL integration tests, `721 passed, 1 skipped`, backend quality, frontend lint/build, base-to-head migration, fresh empty runtime DB, 11-process controller readiness, 8/8 worker health and clean shutdown |

Gate 2 decision: `VERIFIED/CLOSED`. G2-01 through G2-10 pass for the approved controlled
reviewer-demo scope. Commit `652e440495ff0d3a9b8c07baa65a24ae2ed2f023` records exactly
46 paths with `Dhanush R S <dhanushrs981@gmail.com>` as author and committer. The worktree
was clean, the branch push succeeded, local and remote hashes matched, and upstream
tracking was configured. No force push, pull request, merge or deployment occurred. The
final evidence archive SHA-256 is
`fea6daa02efa9cb202a5906b9f463e002caab4d1353b26d698a100b0462227e7`.
At Gate 2 closure Phase 17B still required separate authorization. That authorization and
the later governed evidence are now recorded below; `DEC-033` retains Phase 17B as a
release/submission blocker while `DEC-032` permits deterministic Phase 18 work.

## Phase 17B acceptance

| ID | Requirement | Current status | Gate |
| --- | --- | --- | --- |
| P17B-01 | Preserve and isolate the current benchmark/runtime changes | VERIFIED | committed Phase 17B checkpoint on the approved branch; ignored runtime evidence remains preserved separately |
| P17B-02 | Supported non-duplicate model route | VERIFIED | Groq `openai/gpt-oss-120b` is the sole active evaluation route; Gemini remains disabled |
| P17B-03 | Structured-output contract passes deterministic fixtures | VERIFIED | current focused tests pass |
| P17B-04 | Bounded provider retry and sanitized diagnostics | VERIFIED | focused retry/failover/quota tests pass; no live-provider claim is implied |
| P17B-05 | Frozen corpus remains unchanged during diagnosis | VERIFIED | corpus-v2 remains locked at SHA-256 `814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de` |
| P17B-06 | Provider access/quota preflight | VERIFIED | Groq preflight passed before the single changed-condition revalidation; no application tool executed |
| P17B-07 | Truth-compatible rate | PARTIAL | threshold is at least 80%; unavailable because neither governed Groq attempt completed the corpus |
| P17B-08 | Required-tool selection | PARTIAL | threshold is at least 80%; unavailable because neither governed Groq attempt completed the corpus |
| P17B-09 | Citation validity | PARTIAL | required 100%; unavailable because neither governed Groq attempt completed the corpus |
| P17B-10 | Abstention accuracy | PARTIAL | threshold is at least 80%; unavailable because neither governed Groq attempt completed the corpus |
| P17B-11 | Provider and malformed-output selection gate | PARTIAL | no final report or model-selection result exists; Groq is neither selected nor rejected on model quality |
| P17B-12 | Runtime remains advisory/shadow | VERIFIED | no mutation tool; deterministic pipeline unaffected |
| P17B-13 | Frontend labels incomplete/fallback/abstained truthfully | PARTIAL | committed UI plus browser evidence |
| P17B-14 | Final DB, backend, frontend and security gates | VERIFIED | committed branch retains passing offline, PostgreSQL-backed, frontend and security validation; live selection remains separate |
| P17B-15 | Groq external-blocker receipt observability | PARTIAL | first attempt `3/2/1`; changed-condition revalidation `15/14/1`, 3 completed scenarios, no final report and budget `41/150`; actual request 15 maps to `p17b-04` turn 3, unlike the ideal mocked ordinal schedule; the old receipt lost typed status/reason, while the uncommitted candidate safely adds scenario/turn plus typed allowlisted diagnostics and passes focused `56` plus full backend `871 passed, 1 skipped`; original rejection remains unproved and no full corpus run is authorized |

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

## Unified F-01 to F-50 feature catalogue

These rows map the proposed feature catalogue to existing implementation and tests. They
do not create 50 phases and do not override the active Gate 2 work order. `SC` means
submission/selection-critical; `P1` is important after the safe core; `P2` is optional.

| ID | Requirement / existing mapping | Priority | Status | Repository evidence and tests | Remaining acceptance gate |
| --- | --- | --- | --- | --- | --- |
| F-01 | Signed webhook intake and dedupe; P16-01/02 | SC | VERIFIED | `webhooks.py`, `webhook_ingestion.py`, `webhook.py`; webhook/ingress tests; Gate 1 accepted+duplicate receipt | Provider-emitted Test Mode provenance remains separate under F-38 |
| F-02 | Transactional outbox and workers; P16-09/11/14 | SC | VERIFIED | outbox model/dispatcher/worker, stream consumer, supervision service; outbox/consumer/health tests | Retain Redis interruption and replay regression coverage |
| F-03 | Monotonic payment projection; P15/P16 | SC | VERIFIED | payment projector/state machine/reliability modules and projection/state tests | Keep delayed/reordered/captured-stop cases in final regression |
| F-04 | Evidence-based versioned truth; P15-01–12 | SC | VERIFIED | payment truth models/domain/service, migration chain and truth tests | Provider-backed journey must reuse this resolver, not browser state |
| F-05 | Durable bounded reconciliation; G1A/P16-17 | SC | VERIFIED | committed Gate 1A migration, reconciliation service/worker, 22 focused passes, full controller and controlled restart evidence | Provider-emitted Test Mode provenance remains separate under F-38 |
| F-06 | Ghost failure and late-authorization stop | SC | PARTIAL | state machine, compensation/reconciliation services and late-authorization integration tests exist | Current provider-backed cancellation/duplicate-payment race bundle absent |
| F-07 | Versioned provider failure taxonomy | SC-lite | PARTIAL | Razorpay order error kinds and P16 provider taxonomy tests exist | Confirm mapping/versioning against currently observed provider codes; preserve unknown |
| F-08 | Revenue-risk register and actionable queue | SC | PARTIAL | recovery queue/dashboard services, routes and UI; queue/dashboard tests | Prove totals, priority inputs, empty/error states and no fabricated rows |
| F-09 | Rail health radar and incident hold | P1 | PARTIAL | incident detector/persistence/feed plus intelligence UI and tests exist | Fresh DB/runtime evidence and real-vs-drill provenance remain |
| F-10 | Failure-cohort diagnosis | P1 | PARTIAL | evaluation service and similar-outcomes/investigation paths are precursors | Reproducible sufficient-data comparison and current runtime proof required |
| F-11 | Case-scoped read-only evidence tools; P17-01/02/12 | SC | PARTIAL | merged investigator tool registry/service and focused tool tests | Current PostgreSQL/runtime and provider-ledger proof for every tool remain |
| F-12 | Multi-step bounded investigator; P17-03–05 | SC | PARTIAL | durable investigation model/service and three-path deterministic tests | Phase 17B live selection gate is still broken |
| F-13 | Structured evidence-linked AI claims; P17-06/15 | SC | PARTIAL | Gemini adapter, investigation contracts, API trace and tests exist | Current live citation quality is 30%; reviewer proof remains incomplete |
| F-14 | Deterministic semantic claim verifier; P18-01–04 | SC | NOT IMPLEMENTED | citation presence/ownership checks are not the Phase 18 semantic validator | Implement same-case, cutoff, fact/value, freshness and contradiction validation |
| F-15 | Correct abstention/escalation; P17-08/09 | SC | PARTIAL | deterministic abstention/fallback tests exist and fail-safe rate was recorded | Live abstention accuracy was 0%; Phase 17B threshold remains unmet |
| F-16 | Consent-safe customer message drafter | P1 | PARTIAL | message batch/executor, Resend integration and tests exist | Lock facts, consent, preview, provenance and provider-delivery truth in UI |
| F-17 | Evidence-grounded explanations | P1 | PARTIAL | case detail and AI trace expose hypotheses/citations/fallback labels | Phase 18 validation and Phase 22 why/why-not/change-my-mind proof remain |
| F-18 | Allowed coordinate-free action generator; P18-07–09 | SC | NOT IMPLEMENTED | existing planner/policy is reusable input but not proof of the new capability filter | Generate only feasible intents; backend resolves all trusted coordinates |
| F-19 | Expected-net-recovery ranker; P18-10–12 | P1 | NOT IMPLEMENTED | no accepted calibrated or explicitly `NOT_CALIBRATED` comparative ranker | Store score components, alternatives, exclusions and versioned provenance |
| F-20 | Deterministic policy engine; P19-01/02 | SC | VERIFIED | bounded policy domain/service and broad policy tests exist | Phase 19 must bind it to current truth/action and state-bound approval without weakening hard stops |
| F-21 | Versioned safety controls | SC | PARTIAL | config, policy receipts and Safety Controls UI exist | Persist authorized changes, version them, audit them and prove kill switches |
| F-22 | State-bound approval and invalidation; P19-03–08 | SC | NOT IMPLEMENTED | older token-gated approval is PARTIAL and does not prove the new binding contract | Bind case/truth/evidence/action/amount/expiry; revalidate immediately before execution |
| F-23 | Escalation queue | SC-lite | PARTIAL | case/review queues and approval UI exist | Uncertain/blocked reasons, ownership and end-to-end operator action need proof |
| F-24 | Durable provider intent; P20-01–03 | SC | PARTIAL | recovery action persistence/executor/worker are reusable | Prove commit-before-call, deterministic idempotency and lease ownership under concurrency |
| F-25 | Standard Payment Link lifecycle | SC | PARTIAL | Razorpay link adapter, notifications, recovery action and retrieval tests exist | Verify current Test Mode create/read/cancel/expiry capability and one provider-backed lifecycle |
| F-26 | Crash-window reconciliation; P20-04–06 | SC | NOT IMPLEMENTED | older retry/idempotency tests do not prove provider-success/application-crash recovery | Required lost-persistence test must discover one accepted action without duplication |
| F-27 | Provider-backed Outcome Ledger; P20-09/10 | SC | PARTIAL | outcome models/services/reconciler/UI and tests exist | One current provider-confirmed attributed Test Mode outcome and no double count required |
| F-28 | Tamper-evident Recovery Receipt; P21-07/08 | core SC | NOT IMPLEMENTED | current recovery audit chain is a precursor, not the complete truth-to-outcome receipt | Canonical hash chain, verifier API/UI and tamper detection required |
| F-29 | Explicit stopping rules | SC | PARTIAL | policy, truth invalidation and compensation paths record several stops | Prove already-paid, stale, consent, quota, expired and incident stops across races |
| F-30 | Versioned isolated Scenario Lab; P23-01/08 | SC | PARTIAL | controlled evaluation persistence/service/UI and 48-case lab exist | Freeze seeds/cutoffs/ground truth and keep it isolated from provider-backed accounting |
| F-31 | Comparable strategy/baseline harness; P23-03 | SC | BROKEN | current lab has a zero control baseline and cannot prove incremental recovery | Same frozen evidence/constraints across meaningful arms with case-level export |
| F-32 | “Race” comparison screen | P2 | NOT IMPLEMENTED | no accepted implementation evidence | Optional only after honest comparable metrics pass |
| F-33 | Non-overlapping money waterfall; P23-05 | SC-lite | PARTIAL | outcomes/evaluation UI exists | Define one exact denominator partition and prove bucket reconciliation |
| F-34 | Property-based invariant fuzzing | P1 | NOT IMPLEMENTED | deterministic negative tests exist but no accepted stateful randomized harness | Fuzz event order/concurrency while preserving financial invariants |
| F-35 | Controlled chaos panel | P2 | NOT IMPLEMENTED | failure tests exist; no isolated operator-facing chaos control | Must never touch provider-backed proof or real accounting |
| F-36 | AI quality/adversarial evaluation | SC | BROKEN | live report selected no model: 20% truth/tool, 30% citations, 0% abstention | Deterministic diagnostics then one approved frozen live run meeting locked thresholds |
| F-37 | Reproducible results report | SC | PARTIAL | evaluation/benchmark runners and stored reports exist | One-command versioned report with denominators, failures, limits and case exports |
| F-38 | Guided real Razorpay Test Mode Live Run | SC | PARTIAL | Payment Lab route/services/UI and provider verification code exist | Complete genuine failure→case→action→paid link→attributed outcome path absent |
| F-39 | Merchant Command Center | SC | PARTIAL | dashboard service/API and command-center UI compile and render | Current live-data, empty/error, responsive and protected-action evidence required |
| F-40 | Investigation Room | SC | PARTIAL | deep case page/evidence tabs are a substantial precursor | Phase 22 alternatives, validation, receipt, stale-state and accessibility gates remain |
| F-41 | Rail Radar UI | P1 | PARTIAL | intelligence route/panel and incident feed exist | Show only observed/drill-labelled signals with fresh runtime proof |
| F-42 | Safety Controls UI | SC | PARTIAL | rulebook and Gate 1A worker counters are visible | Responsive/keyboard proof plus authorized persisted/audited edits remain |
| F-43 | Outcomes and waterfall UI | SC | PARTIAL | Outcome Ledger and evaluation dashboards exist | Correct attribution, denominator partition and drilldown proof remain |
| F-44 | Receipt verification UI | P1 | NOT IMPLEMENTED | no accepted receipt-verifier surface | Read-only redacted valid/broken/unavailable result and isolated tamper demo required |
| F-45 | Verified provider-backed run replay | SC | NOT IMPLEMENTED | no accepted genuine completed-run replay evidence | Replay must be read-only, labelled and produce no new actions/metrics |
| F-46 | Protected lab/operator access | SC | PARTIAL | Gate 2 candidate adds signed reviewer sessions, same-origin checks, bounded login attempts and protected reads while retaining specialized mutation tokens | Hosted proxy validation, durable/distributed abuse control and production identity/tenant model remain |
| F-47 | Health, queues, correlation and redacted observability | SC | PARTIAL | public live/ready and protected workers/queues, supervised workers and Gate 1A metrics pass | End-to-end correlation, redaction, abuse signals and hosted operations evidence remain |
| F-48 | Clean-clone reproducibility | SC | PARTIAL | locked installs, controller and migration scripts reproduced locally | One-command empty-provider vs seeded-lab bootstrap from a fresh clone remains |
| F-49 | Protected hosted demo | P1 | NOT IMPLEMENTED | repository is local PowerShell processes plus Compose data services | Deployment/access decision, HTTPS webhook and protected operations required |
| F-50 | Submission documentation and video | SC | NOT IMPLEMENTED | audit docs exist, but README/video/evidence package are incomplete | Final README, architecture, evaluation, limitations, five-minute video and release gate |

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
