# ReclaimRail current state

- Audit date: 31 October 2026
- Gate 1 evidence date: 8 November 2026
- Gate 1A evidence dates: 17–18 November 2026
- Gate 2 final validation evidence date: 18 November 2026
- Gate 2 Git closure evidence date: 18–19 November 2026
- Status refresh date: 19 November 2026
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

It is not currently submission-ready. Gate 1 reproduced the clean committed baseline and
exposed `G1-P0-001`, an unbounded provider-read/evidence-amplification loop. The authorized
Gate 1A candidate now closes that defect with durable per-attempt retry state, bounded
backoff, an explicit budget/circuit, idempotent unavailable evidence, synthetic-provider
blocking and worker metrics. Migrations, focused tests, the complete backend suite,
frontend lint/build and an isolated controlled runtime all passed.

Gate 1A is `VERIFIED` by the owner-authorized local 23-path closure commit recorded in Git
history. The final evidence includes a fresh base-to-head database,
the complete 11-process controller with API ready and 8/8 healthy workers, deterministic
restart/circuit proof, and visually inspected 1024/1440/1920 Safety Controls plus a readable
populated case. The controlled case used a deterministic provider stub and synthetic data;
no live Razorpay verification, provider mutation or live Gemini call was authorized.
Provider-emitted Test Mode provenance remains a separate provider-journey requirement.

The stored live Gemini benchmark still fails its selection gate. The exact Gate 2
candidate clears all known Python and npm production findings, protects operational reads
behind a controlled reviewer session and passes the final Windows/PostgreSQL/controller
gate. npm still reports one unpatched dev-tool advisory as 14 transitive high findings;
the owner accepted that lint/build-only risk for this local controlled-reviewer gate until
an upstream compatible fix exists, with mandatory review before any hosted/public release
or Phase 21 closure. The promised Track 3 measured-recovery evaluation remains synthetic
rather than a comparative outcome study.

## 18 November roadmap reconciliation checkpoint

The unified roadmap was compared with all six audit documents and the recorded Gate 1A
evidence, presented in a reconciliation report and approved by the owner on 18 November
2026. It is now the locked consolidated blueprint. It does not replace the current gate
order, evidence classifications or append-only decision controls.

The proposal's `19 passed, 2 failed` Gate 1A snapshot is obsolete. The append-only work log
records an intermediate `21 passed, 1 failed` run, followed by a corrected focused run of
`22 passed` and a complete backend run of `698 passed, 1 skipped`. The final fresh runtime
and visual evidence closes the remaining technical Gate 1A criteria. The locked documents
and local closure commit complete the administrative gate; no push was authorized.

The 18 November closure preflight stopped before changing files because the worktree had
22 changed paths instead of the recorded 21. The additional path is now identified as
`apps/web/src/app/globals.css`: a responsive Safety Controls/navigation correction. Its
diff was reviewed, `git diff --check` passed and fresh frontend lint/build passed. No
application behavior beyond the preserved candidate, index entry, commit or remote
reference is changed by this documentation reconciliation.

Gate 1A closure criteria:

1. preserve the reviewed exact 22-path worktree;
2. **satisfied:** inspected 1024/1440/1920 Safety Controls evidence is legible and the
   populated case visibly exposes failed/eligible provider truth without washout;
3. **satisfied:** the tracked 11-process controller started against fresh database
   `reclaimrail_gate1a_controller_20261118152748` with API ready and 8/8 healthy workers;
4. **resolved for Gate 1A:** provider-emitted Test Mode proof is deferred to the bounded
   provider-backed journey and remains explicitly `PARTIAL` under Gate 1/F-38;
5. **satisfied:** finalize the six authority documents and unified-roadmap link; and
6. **satisfied:** show the exact staged diff and required identity and create one
   owner-authorized local Gate 1A commit, with no push.

## Gate 2 dependency and controlled-reviewer closure

Gate 2 is `VERIFIED` and `CLOSED` on authoritative branch
`gate2/dependency-access-control` by commit
`652e440495ff0d3a9b8c07baa65a24ae2ed2f023`, whose parent is
`1b26642258ed9e5d3c3b4249d8dc2004050276c9`. The commit contains exactly 46 paths.
Author and committer are `Dhanush R S <dhanushrs981@gmail.com>`. The selected access model
is a controlled, single-merchant reviewer demo. Public liveness/readiness remain public;
workers, queues, dashboard, case, incident, outcome and evaluation reads now require a
server-held reviewer token. The Next.js boundary exchanges the reviewer code once for a
signed, expiring, `HttpOnly`, `SameSite=Strict` cookie. Browser storage no longer holds or
forwards the code. Payment Lab and approval mutations retain their existing specialized
backend tokens and also require a valid reviewer session and same-origin request.

Dependency results on the committed Gate 2 implementation:

- Python runtime and complete locked dependency audits: zero known vulnerabilities;
- npm production audit: zero vulnerabilities;
- Next.js and `eslint-config-next`: `16.4.6`; `sharp`: `0.35.5`; `source-map-js`: `1.2.2`;
- complete npm audit: 14 high findings, all the same unpatched `picomatch` ReDoS advisory
  through lint/build-only dependencies; npm proposes only a breaking forced downgrade to
  `eslint-config-next@14.2.35`, which was not applied; and
- no dependency was force-fixed and no product feature was removed.

Final validation results on the exact 46-path tree later committed unchanged as `652e440`:

- backend format/lint and strict mypy passed for 120 source files;
- protected-route focused suite: `52 passed`;
- Windows/PostgreSQL focused integration: `3 passed`;
- complete backend suite: `721 passed, 1 skipped`;
- base-to-`f8c1b2d3e4a5` migration and schema checks passed on fresh databases;
- frontend lint and Next.js production build passed;
- Python runtime and complete audits found zero known vulnerabilities; npm production
  audit found zero vulnerabilities;
- the complete npm audit's single dev-tool advisory was explicitly accepted under
  `DEC-029`; no force-fix or breaking downgrade was used;
- a fresh runtime database contained zero provider-work candidates;
- all 11 controller processes started, API readiness passed and 8/8 workers were healthy;
- runtime HTTP checks proved public liveness/readiness, protected worker denial/access,
  unauthenticated Payment Lab redirect, protected frontend API denial, signed-cookie login,
  authenticated Payment Lab access and logout;
- runtime logs contained zero Razorpay/Gemini provider-network findings and zero fatal
  findings; no provider mutation or live model request was made;
- all application processes stopped, environment files were restored, and Git retained
  exactly 46 changed paths with zero staged files; and
- final shareable evidence SHA-256:
  `fea6daa02efa9cb202a5906b9f463e002caab4d1353b26d698a100b0462227e7`.

Gate 2 technical acceptance and Git closure are `VERIFIED`. The worktree was clean after
commit and push. The branch was pushed successfully, local and remote commit hashes
matched, and upstream tracking was configured for
`origin/gate2/dependency-access-control`. No force push, pull request, merge or deployment
occurred. This post-commit authority-document refresh does not reopen Gate 2. Phase 17B
remains unauthorized until a separate owner decision.

## Historical Gate 1 baseline reproduction result

Gate 1 was classified `BROKEN` on 8 November. Most foundation gates passed, but a mandatory
runtime path failed and the frontend could not read the required persisted case. No
application code was changed during that reproduction. The Gate 1A section below records
the later corrective candidate; this table is retained as failure history.

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

## Gate 1A P0 remediation closure

The closure commit contains exactly 16 reviewed application/test/frontend paths on parent
`8703bfbd9a3b36dcf4a1af74a1bb04ea76311f5d`, plus seven documentation paths. The sixteenth
application path is `apps/web/src/app/globals.css`, the bounded responsive correction. All
technical and administrative Gate 1A criteria are verified. No push occurred.

| Gate 1A item | Result | Classification |
| --- | --- | --- |
| Durable control persistence | migration `f8c1b2d3e4a5` adds per-attempt reconciliation control; fresh base-to-head upgrade, `current`, `heads` and `check` passed | VERIFIED |
| Cooldown/backoff | repeated polls inside the recorded retry window made zero provider calls | VERIFIED |
| Evidence/truth idempotency | circuit scenario retained 3 evidence rows and truth versions before/after the blocked repeat | VERIFIED |
| Persisted retry budget/circuit | three scheduled unavailable reads opened the durable circuit; restart made zero unexpected calls | VERIFIED |
| Deterministic fail-safe | provider unavailability still resolved to manual investigation and did not enable recovery | VERIFIED |
| Synthetic/live separation | controlled synthetic path was blocked before the provider; provider-call count zero | VERIFIED |
| Provider recovery | after unavailable evidence expired, a deterministic provider result projected `payment_failed` and restored recovery eligibility | VERIFIED |
| Backend focused tests | `22 passed` | VERIFIED |
| Backend complete suite | `698 passed, 1 skipped`; skip remains the known execution-counter race | VERIFIED |
| Backend static quality | Ruff format/lint and strict mypy for 119 source files passed | VERIFIED |
| Frontend compile quality | ESLint and Next.js 16.3.5 production build passed | VERIFIED |
| Controlled runtime | fresh database, isolated Redis DB 15, API ready, target worker healthy, persisted cooldown/circuit/exhaustion/synthetic counters observed | VERIFIED |
| Same controlled case | case `e3aefb14-8df5-4d93-a803-5750f78429e5` rendered readable failed/eligible truth sourced from the deterministic provider adapter | VERIFIED |
| Live Razorpay/Gemini | no live Razorpay call or mutation; no live Gemini call | VERIFIED |
| Full controller rerun | fresh database `reclaimrail_gate1a_controller_20261118152748`; all 11 processes running; API ready; 8/8 workers healthy; sustained check found zero recent fatal findings | VERIFIED |
| Frontend responsive/visual proof | final inspected archive shows unclipped navigation and readable rulebook columns at 1024/1440/1920; the populated 1440 case visibly exposes failed/eligible truth and evidence cards | VERIFIED |
| Provider-emitted Test Mode proof | not authorized or run; explicitly deferred to the provider-backed journey and not mislabelled as Gate 1A evidence | PARTIAL |

The final shareable evidence archive is
`ReclaimRail-Gate1A-Runtime-Evidence-20261118-155209-shareable.zip`, SHA-256
`4af876f59b72da82aa330a0848ac9d29ab8c5175b9325802ca6d09ea92987f71`.

## Repository and Git evidence

| Item | Classification | Evidence |
| --- | --- | --- |
| Remote baseline | VERIFIED | `origin/main` and the local base both resolve to `19126456...` |
| Original Phase 17B worktree cleanliness | BROKEN | 26 changed paths: 19 staged, 12 unstaged and 3 untracked; some paths have both staged and unstaged changes |
| Phase 17B branch commit | PARTIAL | branch exists locally but contains no commit beyond `main`; the implementation is only in the mixed worktree |
| Clean continuation worktree | VERIFIED | the authorized Gate 1A closure commit contains exactly 16 application/test/frontend paths plus 7 documentation paths and leaves the worktree clean |
| Open pull request | NOT IMPLEMENTED | GitHub reports no open pull request for the local Phase 17B work |
| Required current Git identity | VERIFIED | local config is `Dhanush R S <dhanushrs981@gmail.com>` |
| Default-branch authorship | VERIFIED | all 159 commits reachable from current remote `main` use the required identity |
| All-branch authorship hygiene | BROKEN | old remote branches retain 17 AI-authored commits and 110 commits using `dhanushrs981@gamil.com`; they are not reachable from current `main` |
| Remote branch hygiene | OBSOLETE | numerous merged historical phase branches remain; local remote-tracking refs also include branches already deleted on GitHub |
| Tags/releases | NOT IMPLEMENTED | no release/tag evidence was supplied |

The sanitized snapshot intentionally omitted `.env.example` files. Git status says
`apps/api/.env.example` is staged, but its content could not be audited. Do not commit that
file until its diff is reviewed locally for correctness and absence of secrets.

## Original 31 October uploaded-tree verification

| Gate | Result | Classification |
| --- | --- | --- |
| Backend dependency lock install | Gate 2 `uv sync --locked --group dev` passed | VERIFIED |
| Ruff formatting | 253 files already formatted | VERIFIED |
| Ruff lint | all checks passed | VERIFIED |
| Strict mypy | no issues in 120 source files | VERIFIED |
| Backend tests without PostgreSQL | historical audit result: 738 passed, 12 skipped, 3 failed | PARTIAL |
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
| Event reliability and reconciliation | VERIFIED | Gate 1A closes the reproduced amplification defect and passes deterministic, full-controller, responsive and local commit closure |
| Gemini structured recovery planner | PARTIAL | schema-constrained planner with deterministic fallback exists; live quality is not established |
| Gemini Evidence Investigator core | PARTIAL | merged shadow-mode core, durable transcript and 11 read-only tools exist |
| Phase 17B live investigator | PARTIAL | implementation, controlled canary and offline/PostgreSQL validation pass, but two governed Groq corpus attempts did not complete and no model-selection result exists |
| Provider-unavailable reconciliation loop | VERIFIED | Gate 1A controlled runtime proves persisted cooldown/circuit/budget across restart with zero repeat call inside the open circuit |
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

### 20 November 2026 candidate preflight and corpus-contract remediation

The locally configured `gemini-3.6-flash` route passed one bounded Generate Content
preflight: `minimal` thinking, 512 maximum output tokens, 120-second timeout, one SDK
attempt, zero retries, automatic function execution/continuation disabled and forced
`get_truth_snapshot` selection. The returned function was not executed. No Razorpay call
occurred. The report is ignored local evidence and contains no prompt, response or secret.

The first owner-authorized v1 frozen-corpus run did not meet selection thresholds: it made
ten calls (one per scenario, within the ceiling of 90), recorded 100% provider failure and
zero truth-compatible, tool-selection or citation rates. The sanitized report retained no
raw provider payload. Deterministic inspection found that every v1 corpus case ID used a
non-UUID value such as `case-01`, while every declared read-only tool requires a UUID. The
historical v1 corpus and failed report are preserved unchanged. A new UUID-valid v2 corpus
and checksum were added, the runner now rejects malformed case IDs before a provider call,
and safe provider status/reason codes are retained in future sanitized reports. Focused
format, lint, strict mypy and 81 deterministic tests pass.

One separately authorized v2 run subsequently made ten calls (one per scenario, within its
90-request ceiling) and failed at the same full multi-function request boundary before any
tool selection: eight sanitized `400 INVALID_ARGUMENT` rejections and two `429
RESOURCE_EXHAUSTED` quota failures. Truth-compatible, required-tool-selection and citation
rates were all 0%. The UUID correction is therefore necessary validation, but not the final
provider-contract fix. The ignored report is
`.runtime/phase17b/benchmark-gemini-3.6-flash-corpus-v2-20261120.json`; no function or
Razorpay call was executed.

At this historical Gemini checkpoint Phase 17B remained `BROKEN`; later Groq evidence below
supersedes that current classification without establishing a model-quality result.

After the v2 failure, the Gemini adapter was corrected offline to emit only the portable
function-schema subset (`type`, `properties`, `required`, `items`, `enum`) rather than
Pydantic presentation/validation metadata such as `title`, `format` and
`additionalProperties`; backend UUID and strict argument validation remain authoritative.
Focused format/lint, strict mypy and 82 deterministic tests pass. This is a remediation
candidate only. One post-correction full-declaration preflight with a valid UUID made exactly
one request, executed no function and timed out at 120.859 seconds without a model response.
The ignored sanitized report is
`.runtime/phase17b/preflight-gemini-3.6-flash-full-declarations-v2-20261120.json`. The next
work is offline latency/request-shape reduction; another provider request requires separate
authorization.

## Frontend truth

The current frontend builds these surfaces: Live Demo, Command Center, Recovery Cases,
case detail, Human Reviews, Rail Intelligence, Batch Evaluation, Outcome Ledger and Safety
Controls. The case detail page can expose truth, planner, policy, approval, provider action,
outcome and audit evidence. The local untracked components improve investigation citations
and deterministic-fallback labeling but are not committed.

Gate 1A adds a visible provider-read containment rule and live worker counters to Safety
Controls. Automated runtime assertions found the provider call, unavailable, cooldown,
open-circuit, exhausted and synthetic-block values in the rendered UI. Manual inspection
of the final 1024/1440/1920 captures found the navigation and policy table readable without
right-column clipping. The final 1440 populated-case capture visibly shows failed payment
truth, recovery eligibility, immutable cited evidence and provider-unavailable history.

Limitations:

- operational read APIs now require the controlled reviewer token/session, but this is a
  single-merchant demo boundary rather than production tenant/user authorization;
- protected mutations use specialized server-held static secrets plus reviewer-session and
  same-origin checks; production identity, tenant ownership and distributed abuse control
  remain later deployment/Phase 21 requirements;
- there are no automated browser, accessibility or viewport tests;
- Gate 1A has clean responsive screenshots; keyboard/accessibility automation and the
  five-minute judge-path recording remain later Phase 22/submission gates;
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

## 21 November 2026 Phase 17B Groq status

`PARTIAL`: the Phase 17B implementation, successful controlled Groq canary, offline corpus
validation and fresh PostgreSQL-backed validation remain valid. The first governed corpus-v2
attempt ended `INDETERMINATE_TRANSPORT` after `3` starts, `2` responses and `1` indeterminate
request with zero retries. Its checkpoint remains preserved at SHA-256
`38677f99f60ce24be419b9dcf479dd36b543deff9ba592b6afd90c959eda75de`.

One owner-authorized changed-condition corpus revalidation was executed after the external
conditions were reviewed. Preflight passed and the focused wrapper/governor suite reported
`15 passed`. The run had a maximum schedule of 31 request starts and stopped after 15 starts,
14 responses and 1 indeterminate request; it completed 3 scenarios, made 15 SDK attempts,
used zero retries and executed zero application tools. Confirmed usage was 32,746 input tokens
and 2,072 output tokens; the last confirmed `request_remaining` was 986. No final report was
created, so full-corpus thresholds and model selection are unavailable.

The revalidation checkpoint is
`.runtime/phase17b/.groq-corpus-v2-20261121-revalidation.checkpoint.json`, size 5,124 bytes,
SHA-256 `ce227ad68b163d51705f19bc05639a6ebd9721fe4123a194d10f393efe527d28`.
Request 15 was governor-admitted and failed at `provider_boundary` after 1,375 ms against a
configured 60.0-second timeout. The sanitized classification is `provider_rejected`. No HTTP
status, provider code, provider failure kind, timeout result or quota-rejection field was
retained. The evidence therefore does not establish HTTP 400, 429 or 5xx, quota rejection,
transport loss, timeout expiration or model-quality failure; the exact provider cause is
unavailable.

The live budget progressed from `23/150` before the first attempt to `26/150` after its 3
starts, then to `41/150` after the revalidation's 15 starts. One owner-authorized
changed-condition corpus revalidation was executed. No additional execution or retry occurred
after it. `DEC-033` freezes Phase 17B as `PARTIAL` and prohibits another unchanged-condition
corpus run. A future provider revalidation requires materially changed conditions, a versioned
evaluation plan and separate owner authorization.

Phase 17B remains a mandatory release/submission blocker. Groq is neither selected nor rejected
on model quality, no production/model-selection claim exists and no Gemini fallback is
authorized. `DEC-032` remains valid and permits deterministic, provider-neutral Phase 18 work
while this external blocker remains; Phase 18 has not begun and Phase 19 is not authorized.

### Request-15 offline diagnosis and validation candidate

The owner chose to continue Phase 17B rather than begin the Phase 18 work permitted by
`DEC-032`. Actual live receipt boundaries take precedence over the ideal mocked schedule:
the retained input-token resets show requests 13–15 belong to the in-progress `p17b-04`
conversation, so request 15 is actual turn 3. In the ideal 31-request mocked schedule,
ordinal 15 would instead be `p17b-05` turn 3. The old checkpoint does not retain the two
preceding tool names, typed provider status or provider reason.

Offline reconstruction validates the request shape without establishing why the provider
rejected it: roles and tool-call correlation are ordered, parallel tool calls are disabled,
choice is the generic `required` mode, all 11 read-only plus 2 terminal declarations remain
available and schemas use the portable subset. `provider_rejected` alone does not establish
an HTTP status, quota failure, timeout, transport loss, payload defect or model-quality result.

The uncommitted diagnostic candidate adds only validated frozen scenario ID/turn and typed,
allowlisted HTTP status, provider reason and rate-limit metadata to future receipts. Tests
prove both a typed HTTP rejection and a provider exception with no HTTP response; raw
exception text, prompts, evidence, response bodies, arbitrary headers/status text, opaque
IDs and secrets remain excluded. This improves future evidence but has not proved or fixed
the original provider rejection.

Final offline validation used the existing isolated healthy PostgreSQL 17.11 container at
`127.0.0.1:55433` with its established process-local credentials. TCP `SELECT 1` passed;
Alembic current/heads were `b17b9c3d4e5f (head)` and `alembic check` found no new upgrade
operations. Ruff format/lint and strict mypy for 130 source files passed, focused tests were
`56 passed`, and the complete backend suite was `871 passed, 1 skipped`. Final JUnit SHA-256:
`e2e0839c6df8814302378e413fb11fca3ce4356e06ce93efc5165c81ecb01c64`.

Phase 17B remains `PARTIAL` and blocks release/submission. The live budget remains `41/150`:
the first corpus attempt recorded `3/2/1` starts/responses/indeterminate; the one authorized
changed-condition revalidation recorded `15/14/1`, 3 completed scenarios and no final report
or quality verdict. No full corpus run is currently authorized. The next live action requires
a separately reviewed, narrowly bounded diagnostic plan. Gemini remains disabled; AI remains
read-only and advisory.

### p17b-04 bounded diagnostic wrapper — offline implementation

The evaluation-only `p17b-04` diagnostic wrapper is now implemented without changing the
frozen corpus, checksum, provider adapter, governor, authoritative turn engine, prompts,
fixtures, thresholds, model ordering, persistence, frontend or application services. It
loads the locked corpus-v2 at SHA-256
`814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de`, selects exactly
`p17b-04`, begins at turn 1 and delegates all turns to `run_frozen_scenario`. Provider-selected
tools determine subsequent frozen observations; the wrapper contains no forced function,
historical tool name, historical argument, fabricated opaque ID or application-tool executor.

The wrapper requires separate exact acknowledgements for the starting budget `41/150` and a
future owner-authorized live diagnostic. It has independent engine and transport ceilings of
three request starts, zero retries and no failover. New output and checkpoint paths must be
unused JSON files under ignored `.runtime/phase17b`. Artifacts retain only sanitized request
coordinates, counters/timings and typed allowlisted provider diagnostics. A three-start run
without a terminal response is labelled `incomplete_request_ceiling`; every artifact states
that corpus verdict and model selection were not evaluated.

The first offline implementation validation passed Ruff, strict mypy and a focused mocked
suite with `67 passed`. A subsequent read-only review found that every schema-valid terminal
turn was labelled successful even when the authoritative engine reported invalid citations or
`failed_safe=false`. That unsafe success signal was corrected: those terminals now produce
`unsafe_terminal_response`, retain only the engine's boolean `citations_valid` result and exit
nonzero. A safe early abstention remains a terminal diagnostic response without becoming a
quality verdict. New tests cover unseen citations, forbidden summary content, sanitized output
and checkpoint artifacts, and cancellation after request start.

Corrected offline validation passed: the isolated diagnostic suite reported `19 passed in
1.84s`; Ruff format check reported `253 files already formatted`; final Ruff lint passed after
one import-order correction; strict mypy passed for 130 source files; and the complete focused
Phase 17B suite reported `70 passed in 7.65s`. No Groq, Gemini, Razorpay, PostgreSQL, worker,
corpus, canary or application-tool execution occurred. No runtime artifact was created.

A further offline review found that the three-start counter was scoped to one wrapper process:
two simultaneous invocations could each pass preflight and reserve three starts, and same-path
invocations could race before the first checkpoint existed. The wrapper now acquires one
process-visible exclusive lease in `.runtime/phase17b` before credentials or transport and
rechecks both destinations inside the lease. A concurrent or stale lease fails closed and is
not removed by the rejected invocation; cancellation releases the lease while preserving its
sanitized checkpoint. The expanded isolated suite reported `21 passed in 1.93s`; final Ruff
format/lint and strict mypy passed; and the complete focused suite reported `72 passed in
8.40s`.

This offline wrapper does not explain the historical request-15 rejection and does not select
or reject Groq on quality. The exact provider rejection cause remains unknown, the live budget
remains `41/150`, and Phase 17B remains `PARTIAL` and a release/submission blocker. Running the
wrapper still requires separate owner authorization; the budget acknowledgement alone is not
authorization.

### p17b-04 diagnostic retention correction and owner-authorized run

`DEC-034` authorizes bounded per-turn diagnostic retention for synthetic frozen-corpus
diagnostics only. The Groq adapter now exposes an in-memory, already-validated call seam to the
diagnostic wrapper; the wrapper persists only typed allowlisted status/reason, scrubbed message
prefixes, tool name, bounded scrubbed arguments, call ID, finish reason, turn type and local
validation reason. Headers, keys, bearer tokens, raw payloads, prompts, customer data and
unsanitized provider text remain forbidden.

The previous report and checkpoint remain unchanged and are preserved as evidence: three
responses, `malformed_output=true`, no retained diagnostic fields. One newly authorized run was
then executed from p17b-04 turn 1 with Groq `openai/gpt-oss-120b`, six maximum starts, 60-second
timeout, zero retries and no failover. It used six model-selected read-only tools and stopped at
the request ceiling without a terminal answer or provider error. The retained per-turn call
IDs, tool names and case-ID arguments are in the ignored v2 report/checkpoint; no HTTP/provider
error fields were present because no provider rejection occurred.

The result remains `incomplete_request_ceiling`, with `corpus_verdict=not_evaluated` and
`model_selection=not_evaluated`. The engine marks budget exhaustion as `malformed_output=true`
even though all six observed responses were tool calls; this is an existing engine result, not
evidence of a malformed provider payload. The live budget is now `50/150`. Phase 17B remains
`PARTIAL`; Groq is neither selected nor rejected on quality.

Full-corpus preparation is implemented offline: DEC-034 per-turn retention, 2.5-second pacing,
sanitized rate-limit metadata, exclusive run lease and continue-on-failure denominator handling.
The engine maximum is nine turns per scenario; the diagnostic six-start ceiling was separate. The
authorized run ceiling is 90 starts and the total live cap is 250. The one authorized run completed
with 16 starts, 15 responses and one indeterminate request. p17b-03 recorded sanitized HTTP 400
`provider_rejected`; p17b-04 through p17b-10 were retained as governor-refused failed cases, so
all ten scenarios remain denominated. The report exit was nonzero because thresholds failed. The
budget is 66/250. This does not select or reject Groq on model quality; Phase 17B remains `PARTIAL`.

Offline review correction: definitive HTTP/provider rejection now fails only the current scenario;
timeout, transient and unknown provider outcomes still stop the run. Groq tool-result messages use
standard role/tool_call_id/content linkage. The retained report did not keep tool declarations,
tool_choice or full request messages, so the exact 400 cause remains unknown; the request-shape
change is a compatibility hypothesis, not proof. Offline validation passed with 52 focused tests,
Ruff, strict mypy and diff check. No live call was made; budget remains 66/250.

The one owner-authorized 22 November corpus run completed with 30 starts, 26 responses and four
provider failures. Retained HTTP 400 details identify `tool_use_failed` in p17b-02, p17b-04 and
p17b-07; a transient failure in p17b-08 stopped subsequent transport. All ten scenarios remain
in denominators. Locked thresholds failed; budget is 96/250. Phase 17B remains `PARTIAL`.

23 November offline candidate: one retry per model turn for tool_use_failed or transient/timeout,
persisted attempt receipts and backoff, and a two-consecutive-final-transient stop rule passed
focused mocked tests. No corpus rerun occurred. The one authorized model-list read supplied IDs
but no tool-calling capability metadata. Phase 17B remains `PARTIAL`; budget remains 96/250.

The one owner-authorized versioned-prompt run recorded 37 starts, 30 responses and five retries.
Two scenarios ended in HTTP 400 tool_use_failed; the local estimated day token guard refused
p17b-09 after one tool response and p17b-10 before transport. The ten-row report fails locked
thresholds and is not a complete provider evaluation. Prompt SHA-256 is
`687bbc1f3661030b9adcb43a9c270d3a21633c0c2474d8e86be152c815b3bb75`.
Phase 17B remains `PARTIAL`; live budget is 133/250.

23 November Mistral candidate: `RECLAIMRAIL_MISTRAL_API_KEY` is present and `.env` is ignored.
A separate evaluation-only adapter and bounded smoke runner passed offline focused tests, Ruff,
strict mypy and diff check. The one authorized Mistral `GET /v1/models` returned HTTP 200, but
`mistral-large-2512` was absent from the returned chat/function-calling-capable set. The smoke
stopped after this one request; no plain chat or forced tool call was made. This does not prove
whether the model ID was absent entirely or present without the required capability flags,
because the sanitized artifact retained only eligible model IDs. Phase 17B remains `PARTIAL`;
historical Groq budget stays 133/250.

23 November Mistral medium continuation: the preserved authenticated model-list artifact
identified `mistral-medium-latest` as chat and function-calling capable. A closed target status
(`absent_from_model_list`, `present_but_not_chat_tool_capable`, `eligible`) replaced broad model
metadata in future smoke reports. Offline gates passed. The two additional authorized POSTs
were plain chat (HTTP 429, 594 ms) and forced read-only tool choice (HTTP 429, 453 ms), each one
attempt with no retry/failover. No completion, returned model ID, token usage, rate-limit number,
tool call or tool execution was observed. Mistral is not technically verified for corpus
evaluation. Phase 17B remains `PARTIAL`; Groq budget remains 133/250.

## 24 November 2026 Gemini 3.8 Flash isolated smoke

`PARTIAL`: the owner authorized only a three-slot smoke using the isolated
`RECLAIMRAIL_GEMINI_38_API_KEY`; the variable was present and `apps/api/.env` remained ignored.
The isolated evaluation path uses Google Gen AI SDK 2.34.0 and the current Interactions API,
sets a 60-second timeout, disables SDK continuation, configures one transport attempt with no
retry or failover, declares only the real 11 Phase 17B read-only functions, and never submits a
function result or invokes an application tool. It does not use the historical Gemini key or
the historical `gemini-3.6-flash` Generate Content request shape.

Offline validation passed: Ruff reported 259 files already formatted and all lint checks passed;
strict mypy reported no issues in 132 source files; the focused Gemini/Phase 17B provider and
evaluation suite reported `170 passed in 12.35s`; and `git diff --check` passed. The authenticated
model-metadata request returned HTTP 200 in 593 ms and returned exactly `gemini-3.8-flash`.
The plain Interactions request then timed out at exactly 60,000 ms with one transport attempt,
no HTTP status, provider response, returned model, token usage or quota metadata. It therefore
did not return exactly `OK`. The runner stopped before the forced-function request, as required.

The two ignored sanitized artifacts are
`.runtime/phase17b/gemini38-smoke-20261124T052546Z-1-model_metadata.json` and
`.runtime/phase17b/gemini38-smoke-20261124T052546Z-2-plain.json`. They contain no key, header,
prompt, raw body, arbitrary provider message, opaque ID, function result or private evidence.
No corpus, canary, diagnostic scenario, Razorpay, Groq, Mistral, PostgreSQL, worker,
evidence-service or application-tool execution occurred. Gemini 3.8 Flash access is confirmed,
but plain inference and function calling are not technically verified; it is not ready for a
separately authorized evaluation plan. Phase 17B remains `PARTIAL`, no provider is selected, and
the historical Groq budget/evidence remains unchanged at `133/250`.

## 24 November 2026 Gemini 4 Hydrogen isolated smoke

`PARTIAL`: the authenticated project catalog previously listed `gemini-4-hydrogen`, but that
catalog visibility was not treated as generation access and the model-list request was not
repeated. Official Google Interactions documentation identifies `low` as Hydrogen's lowest
supported thinking level. The isolated smoke path now accepts an explicit allowlisted model,
retains the historical Gemini 3.8 behavior, allows Hydrogen without enabling Neon, Argon or
Carbon, and fixes future model-list sanitation to read the SDK's current `supported_actions`
field. No frozen corpus, prompt, threshold or application service changed.

Offline validation passed: Ruff reported 259 files already formatted and all lint checks passed;
strict mypy reported no issues in 132 source files; the focused Gemini/Phase 17B provider and
evaluation suite reported `175 passed in 12.43s`; and `git diff --check` passed. Hydrogen requests
use `thinking_level=low`, maximum 256 output tokens, a 120-second timeout, one SDK attempt, zero
retry/failover, disabled continuation and no function executor.

The single started live request was the plain Interactions request. It returned HTTP 503 after
31,891 ms, classified `provider_unavailable`, with safe quota metadata
`retry_after_seconds=30`. It returned no model response, exact `OK`, model ID or input/output/
thinking-token counts. The runner stopped before the forced `get_truth_snapshot` request. The
new ignored sanitized receipt is
`.runtime/phase17b/gemini4-hydrogen-smoke-20261124T054256Z-1-plain.json`.

Hydrogen generation access and function calling remain unconfirmed. It is not technically ready
for a separately reviewed evaluation plan and is not selected. Phase 17B remains `PARTIAL`; the
historical Groq budget/evidence remains unchanged at `133/250`. No Groq, Mistral, Razorpay,
PostgreSQL, worker, evidence-service or application-tool execution occurred.

## 24 November 2026 Gemini controlled-canary diagnostic

`PARTIAL`: receipts now retain one bounded `validation_failure_reason` per parser branch without
raw arguments or IDs. Prompt, linkage, frozen observations and the no-tool-execution boundary were
unchanged. The combined ceiling was six starts, enforced as three per model. Ruff format/lint,
strict mypy for 134 source files, 196 focused tests and `git diff --check` passed.
`gemini-3.5-flash` and `gemini-4-hydrogen` each made one request and received HTTP 503 with
retry-after 30 seconds before a model response. Both failed safe with zero retries/failover. No
parser reason, citations or truth compatibility could be evaluated; the earlier malformed turn
remains unexplained.

## 24 November 2026 offline Gemini resilience candidate

`PARTIAL`: the read-only Gemini investigator now accepts settings-backed primary and optional
fallback models. HTTP 429/503 receives at most two retries per model, using bounded Retry-After
when available and deterministic backoff otherwise, before fallback. Successful requests log only
the served and requested model names. The canary runner persists its sanitized report before
client cleanup and retains the result if cleanup fails. Ruff format/lint, strict mypy for 134
source files, 220 focused tests and `git diff --check` passed. No API request or live canary ran.
