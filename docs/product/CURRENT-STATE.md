# ReclaimRail current state

- Audit date: 31 October 2026
- Gate 1 evidence date: 8 November 2026
- Status refresh date: 17 November 2026
- Audit source: sanitized local snapshot `ReclaimRail-Audit-20261031-220531.zip`
- Public repository: `https://github.com/dhanushgowdars/ReclaimRail`
- Remote `main`: `19126456b37d21d1ead659762c5f92916f3a64e1`
- Audited mixed-worktree branch: `phase-17b/live-investigator-closure`
- Clean continuation branch: `audit/current-state-reset`
- Both branch commits before the audit-document commit: same as remote `main`
- Audit rule: repository evidence overrides earlier chat claims

## Executive status

ReclaimRail is a substantial, structured prototype rather than an empty or fake project.
Its committed baseline contains real FastAPI services, PostgreSQL models and migrations,
Redis-backed workers, Razorpay Test Mode adapters, deterministic payment truth and policy,
provider reconciliation, a Next.js operations console and a large automated test suite.

It is not currently submission-ready. Gate 1 reproduced the clean committed baseline on
Windows/Docker and verified migrations, backend quality, frontend compilation, full-stack
startup, signed webhook intake, idempotency and payment projection. It also exposed a P0
runtime defect: the Payment Lab recovery worker performed an unbounded provider-read loop
after provider unavailability, appended equivalent timestamp-unique evidence and advanced
payment-truth versions without new external information. The tested payment was moved to
`manual_investigation_required`, so the required persisted recovery case and same-case
frontend proof could not be completed.

The stored live Gemini benchmark still fails its selection gate, dependency audits retain
known vulnerabilities, and the promised Track 3 measured-recovery evaluation remains
synthetic rather than a comparative outcome study.

## Gate 1 baseline reproduction result

Gate 1 is `BROKEN`, not complete. Most foundation gates passed, but a mandatory runtime
path failed and the frontend could not read the required persisted case. No application
code was changed to work around the failure.

| Gate 1 item | Result | Classification |
| --- | --- | --- |
| Clean audit branch | `audit/current-state-reset` at `8dc1655cfae5ac3507e82d766e81b463cdf617dd`; worktree clean before and after reproduction | VERIFIED |
| Git identity | `Dhanush R S <dhanushrs981@gmail.com>` | VERIFIED |
| Locked dependencies | `uv sync --locked --group dev` and CI-pinned npm install passed; lockfile hashes unchanged | VERIFIED |
| Isolated infrastructure | PostgreSQL 17.11 on `127.0.0.1:55432`; Redis 8.10.1 on `127.0.0.1:16379`; both healthy | VERIFIED |
| Redis port recovery | Windows excluded `56300-56399`; only ignored local environment values were changed from `56379` to `16379` | VERIFIED |
| Alembic | base-to-`e7a1c2d3f417` upgrade passed; `current`, `heads` and `check` passed; no new operations detected | VERIFIED |
| Backend quality | Ruff format/lint passed; strict mypy passed for 119 source files; pytest `686 passed, 1 skipped` | VERIFIED |
| Explained skip | known persisted execution-counter integration race; provider idempotency is covered separately | PARTIAL |
| Frontend quality | ESLint and Next.js 16.3.5 production build passed; all expected routes compiled | VERIFIED |
| Frontend automated behavior | no frontend unit/E2E suite exists | NOT IMPLEMENTED |
| Full controller startup | 11 processes started; API ready; 8/8 workers initially healthy | VERIFIED |
| Browser smoke evidence | Payment Lab rendered at `http://127.0.0.1:3000/payment-lab` | VERIFIED |
| Signed webhook receipt | first delivery `202 accepted`; replay `200 duplicate`; same canonical event | VERIFIED |
| Webhook persistence | one canonical event, delivery count two, processing status `processed` | VERIFIED |
| Payment projection | one `unknown -> failed` applied transition from verified webhook evidence | VERIFIED |
| Evidence provenance | payload was locally signed controlled synthetic evidence, not a provider-emitted Razorpay Test Mode webhook | PARTIAL |
| Provider-read containment | 453/453 logged reconciliation batches reported `unavailable=1`; no durable cross-batch circuit opened | BROKEN |
| Evidence/truth boundedness | diagnostic sample reached 128 evidence records and truth version 127 while the loop was running | BROKEN |
| Recovery eligibility | changed to false after truth became `manual_investigation_required` | BROKEN |
| Persisted recovery case | case service correctly refused creation with `recovery_not_eligible` | BROKEN |
| Same-case frontend proof | impossible because no eligible case was created | BROKEN |
| Provider mutation/money movement | no recovery case, action, approval, outcome or money-moving provider execution occurred | VERIFIED |
| Provider reads | repeated Razorpay Test Mode read attempts occurred in the background worker; the earlier command-only `RazorpayApiCalled=False` line was incomplete system-level evidence | BROKEN |
| Gemini | shadow disabled; no live Gemini corpus or request was run | VERIFIED |

### P0 defect: unbounded provider-unavailable reconciliation

**ID:** `G1-P0-001`

The reproducible chain is:

1. a locally signed controlled synthetic `payment.failed` event is accepted once and its
   duplicate is recognized;
2. payment state projects to `failed` and initial evidence resolves the failure;
3. after reconciliation becomes eligible, the live Razorpay order adapter cannot verify
   the synthetic order/payment identifiers;
4. `payment_truth_reconciliation._record_unavailable` writes authoritative
   `provider.available=false` evidence whose source reference contains the observation
   timestamp;
5. truth becomes `manual_investigation_required`;
6. the candidate query immediately reselects that state on every worker poll, independent
   of `RECONCILE_AFTER`;
7. every poll creates another unique evidence row and truth snapshot; and
8. the per-batch circuit breaker never opens across batches when only one candidate fails.

Observed runtime evidence: 453 reconciliation log lines, 453 batches with provider
unavailable, `projected=0`, `persistence_failures=0`, and `circuit_opened=False`. The final
controller stop terminated all 11 application processes. PostgreSQL and Redis were left
preserved for audit evidence.

## Repository and Git evidence

| Item | Classification | Evidence |
| --- | --- | --- |
| Remote baseline | VERIFIED | `origin/main` and the local base both resolve to `19126456...` |
| Original Phase 17B worktree cleanliness | BROKEN | 26 changed paths: 19 staged, 12 unstaged and 3 untracked; some paths have both staged and unstaged changes |
| Phase 17B branch commit | PARTIAL | branch exists locally but contains no commit beyond `main`; the implementation is only in the mixed worktree |
| Clean continuation worktree | VERIFIED | `audit/current-state-reset` was created from `19126456...`; only the six audit documents differ and zero application paths changed |
| Open pull request | NOT IMPLEMENTED | GitHub reports no open pull request for the local Phase 17B work |
| Required current Git identity | VERIFIED | local config is `Dhanush R S <dhanushrs981@gmail.com>` |
| Default-branch authorship | VERIFIED | all 159 commits reachable from current remote `main` use the required identity |
| All-branch authorship hygiene | BROKEN | old remote branches retain 17 AI-authored commits and 110 commits using `dhanushrs981@gamil.com`; they are not reachable from current `main` |
| Remote branch hygiene | OBSOLETE | numerous merged historical phase branches remain; local remote-tracking refs also include branches already deleted on GitHub |
| Tags/releases | NOT IMPLEMENTED | no release/tag evidence was supplied |

The sanitized snapshot intentionally omitted `.env.example` files. Git status says
`apps/api/.env.example` is staged, but its content could not be audited. Do not commit that
file until its diff is reviewed locally for correctness and absence of secrets.

## Verification performed on the uploaded working tree

| Gate | Result | Classification |
| --- | --- | --- |
| Backend dependency lock install | `uv sync --locked --group dev` passed | VERIFIED |
| Ruff formatting | 253 files already formatted | VERIFIED |
| Ruff lint | all checks passed | VERIFIED |
| Strict mypy | no issues in 120 source files | VERIFIED |
| Backend tests without PostgreSQL | 738 passed, 12 skipped, 3 failed | PARTIAL |
| Reason for three failures | integration tests could not start because `RECLAIMRAIL_DATABASE_URL` was not configured | PARTIAL |
| Alembic graph | one head: `e7a1c2d3f417` | VERIFIED |
| Alembic upgrade/check | not run; no PostgreSQL service in the audit environment | PARTIAL |
| Frontend locked install | `npm ci --include=optional` passed | VERIFIED |
| Frontend lint | passed | VERIFIED |
| Frontend production build | passed; 11 application/API routes generated | VERIFIED |
| Frontend automated behavior tests | no test script or E2E suite exists | NOT IMPLEMENTED |
| Frontend visual/accessibility evidence | no current screenshot, viewport or keyboard gate supplied | NOT IMPLEMENTED |
| Python dependency audit | 10 known findings in 4 installed packages | BROKEN |
| npm production dependency audit | 3 findings: 1 critical, 2 high | BROKEN |
| GitHub CI at committed baseline | backend and frontend jobs passed on 26 September 2026; this does not cover local WIP | VERIFIED |
| Live Gemini evidence | no call was made by design; the latest supplied report remains the applicable evidence | PARTIAL |

The three backend test failures are not treated as product assertion failures, but they
prevent a fresh full-suite completion claim. The old green CI run proves the committed
baseline, not the uncommitted Phase 17B state.

## Capability audit

| Capability | Classification | Repository evidence and limitation |
| --- | --- | --- |
| Signed Razorpay webhook ingestion | VERIFIED | raw-body HMAC, size limit, durable intake, idempotency and tests exist |
| Transactional outbox and Redis processing | VERIFIED | models, dispatcher, consumer, retry/DLQ logic and tests exist; current DB gate not rerun |
| Deterministic payment state machine | VERIFIED | monotonic transitions, duplicate handling and late authorization are tested |
| Incident detection | VERIFIED | robust window detector and worker paths exist; current PostgreSQL integration rerun is blocked |
| Bounded recovery policy | VERIFIED | deterministic guardrails, check receipts and broad unit coverage exist |
| Human approval | PARTIAL | protected token-gated workflow exists and is visible; it uses shared demo/operator secrets, not user authentication |
| Durable Payment Link execution | PARTIAL | idempotent adapter, intent and reconciliation paths exist; no current live end-to-end evidence bundle was supplied |
| Outcome Ledger | PARTIAL | provider-confirmed/pending distinctions are implemented; no current database/live replay was reproduced |
| Versioned payment truth | VERIFIED | append-only evidence and immutable snapshot models, resolver and tests exist; database migration rerun pending |
| Event reliability and reconciliation | VERIFIED | error taxonomy, stale-event policy, circuit breaker, replay and invalidation logic exist; database rerun pending |
| Gemini structured recovery planner | PARTIAL | schema-constrained planner with deterministic fallback exists; live quality is not established |
| Gemini Evidence Investigator core | PARTIAL | merged shadow-mode core, durable transcript and 11 read-only tools exist |
| Phase 17B live investigator | BROKEN | latest report selected no model and failed locked quality thresholds |
| Provider-unavailable reconciliation loop | BROKEN | `G1-P0-001`: provider reads, evidence rows and truth versions amplify without new information |
| Evidence-claim semantic validator | NOT IMPLEMENTED | explicitly deferred to Phase 18 |
| Comparative action ranking | NOT IMPLEMENTED | Phase 18 |
| State-bound approval redesign | NOT IMPLEMENTED | Phase 19 acceptance contract |
| Ambiguous durable execution protocol | NOT IMPLEMENTED | Phase 20 acceptance contract; older executor is useful input, not proof of the new phase |
| Signed recovery receipt/security closure | NOT IMPLEMENTED | Phase 21 |
| Investigation Room | NOT IMPLEMENTED | Phase 22; current case trace is a partial precursor |
| Track 3 measured batch evaluation | BROKEN | current 48-case lab is controlled synthetic policy evidence with a zero control baseline; it cannot prove incremental recovery |
| Public deployment | NOT IMPLEMENTED | Compose provisions only PostgreSQL/Redis; runtime is local PowerShell processes and architecture says deployment is deferred |
| Demo video | NOT IMPLEMENTED | README contains `Demo: <add-video-link>` |

## Phase 17B live evidence

The newest supplied real-model report is
`.runtime/phase17b-live-final-v3.json`, generated 3 October 2026. It is ignored runtime
evidence, not committed acceptance evidence.

| Metric | Recorded result | Required result |
| --- | ---: | ---: |
| Selected model | none | one eligible model |
| Truth-compatible rate | 20% | at least 80% |
| Required-tool selection | 20% | at least 80% |
| Citation validity | 30% | 100% |
| Abstention accuracy | 0% | at least 80% |
| Provider failure rate | 60% | 0% for selection |
| Malformed-output rate | 0% | 0% |
| Failed-safe rate | 70% | informational; safety fallback worked |
| p95 latency | 34,523 ms | no final product budget approved |

Two scenarios passed completely. One additional scenario completed with valid citations but
did not select the required tools. Prompt-injection evidence failed safely. Six scenarios
failed at the provider boundary, mainly with HTTP 429. This proves safe degradation, not
acceptable live investigation quality.

The configured investigator route includes `gemini-3.7-flash`. Google now documents that
identifier as deprecated and automatically routed to `gemini-3.8-flash`; it is an obsolete
duplicate route, not independent failover capacity. No model-string change is authorized
until the Phase 17B remediation specification is approved.

## Frontend truth

The current frontend builds these surfaces: Live Demo, Command Center, Recovery Cases,
case detail, Human Reviews, Rail Intelligence, Batch Evaluation, Outcome Ledger and Safety
Controls. The case detail page can expose truth, planner, policy, approval, provider action,
outcome and audit evidence. The local untracked components improve investigation citations
and deterministic-fallback labeling but are not committed.

Limitations:

- most read-only recovery APIs have no authentication or merchant/user authorization;
- protected mutations use shared static secrets intended for a controlled demo;
- there are no automated browser, accessibility or viewport tests;
- no current screenshot or five-minute judge-path recording accompanies the snapshot;
- build success proves compilation, not that live backend state is understandable in every
  empty, error, pending and terminal condition.

## Documentation and repository hygiene

| Item | Classification | Finding |
| --- | --- | --- |
| Root `AGENTS.md` | VERIFIED | added by this audit; repository-wide working rules were absent in the supplied snapshot |
| Current-state/decision/acceptance/work-log docs | VERIFIED | added by this audit; the requested governance files were absent in the supplied snapshot |
| `docs/contracts.md` diagnostic-tool description | OBSOLETE | describes four tools while Phase 17 uses 11 |
| `docs/phase-14-safety-contracts.md` status | OBSOLETE | still says PostgreSQL CI is pending |
| README demo evidence | BROKEN | video URL is a placeholder; one demo step is duplicated; repository tree names `docker-compose.yml` although the file is `compose.yaml` |
| README end-to-end claim | PARTIAL | claims both Test Mode paths were exercised, but the supplied snapshot contains no current reproducible acceptance bundle |
| Tracked backup patch/directories | OBSOLETE | `before-phase-13d-progress.patch` and `untracked-backup-before-phase-13d/` are historical debris |
| Ignored `.runtime` backups/reports | PARTIAL | useful audit evidence exists, but obsolete backup copies and failed reports need an explicit retention decision |

## Immediate blockers before feature implementation

1. Owner review of this Gate 1 closure and explicit authorization for a dedicated
   `G1-P0-001` remediation phase. No application fix is authorized by this document.
2. Bound provider reconciliation across polls, deduplicate equivalent unavailable
   evidence and prove a durable request budget/cooldown before restarting the full worker.
3. Re-run Gate 1 from a fresh isolated database and complete a provider-truthful persisted
   case plus same-case frontend proof.
4. Remediate and re-audit backend/frontend dependencies in a dedicated phase.
5. Decide the Phase 17B model, quota and benchmark strategy before one controlled rerun.
6. Resolve remaining documentation contradictions and create a committed evidence bundle.
