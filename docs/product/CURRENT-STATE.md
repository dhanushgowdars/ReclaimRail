# ReclaimRail current state

- Audit date: 31 October 2026
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

It is not currently submission-ready. The local checkout is a mixed Phase 17B worktree,
the stored live Gemini benchmark fails its selection gate, current dependency audits find
known vulnerabilities, the current full PostgreSQL gate was not reproduced in this audit,
and the promised Track 3 measured-recovery evaluation remains synthetic rather than a
comparative outcome study.

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

1. Owner approval to begin Gate 1 baseline reproduction; implementation remains
   unauthorized until that separate decision.
2. Reproduce PostgreSQL migrations and the full backend suite on Windows/Docker.
3. Remediate and re-audit backend/frontend dependencies in a dedicated phase.
4. Decide the Phase 17B model, quota and benchmark strategy before one controlled rerun.
5. Resolve remaining documentation contradictions and create a committed evidence bundle.
