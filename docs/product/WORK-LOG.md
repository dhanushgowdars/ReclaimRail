# ReclaimRail work log

Append-only. Do not rewrite failed results to make a later run look clean. Record a new
entry explaining the correction.

## 31 October 2026 — repository reset audit

### Scope

- Read-only audit of the uploaded local snapshot and the public GitHub repository.
- No application code, dependency, runtime configuration, Git reference or provider state changed.
- No live Gemini request was executed.

### Repository evidence

- Public remote `main`: `19126456b37d21d1ead659762c5f92916f3a64e1`.
- Local base: same commit.
- Local branch: `phase-17b/live-investigator-closure`.
- Worktree: 26 changed paths; 19 staged, 12 unstaged, 3 untracked.
- Git identity: `Dhanush R S <dhanushrs981@gmail.com>`.
- GitHub open pull requests: none.
- GitHub checks for `1912645`: Backend quality and Frontend quality both succeeded on
  26 September 2026.
- Default branch: 159 commits, all with the required owner identity.
- Other remote branches: retain wrong-email and AI-authored historical commits; no cleanup performed.

### Commands and results

| Command | Result |
| --- | --- |
| archive path-safety and inventory check | 407 entries; 4,363,449 uncompressed bytes; zero unsafe paths |
| `git ls-remote --heads ...` | remote `main` matched the local base; stale local remote refs identified |
| `uv sync --locked --group dev` | passed |
| `uv run --frozen ruff format --check .` | 253 files already formatted |
| `uv run --frozen ruff check .` | passed |
| `uv run --frozen mypy app` | passed; 120 source files |
| `uv run --frozen pytest -q` | 738 passed, 12 skipped, 3 failed because no database URL was configured |
| `uv run --frozen alembic heads` | one head, `e7a1c2d3f417` |
| `npm ci --include=optional` | passed; 368 packages installed |
| `npm run lint` | passed |
| `npm run build` | passed; all current routes compiled |
| `npm audit --omit=dev` | failed: 1 critical and 2 high findings |
| project-site-packages `pip-audit` | failed: 10 known findings in 4 packages |
| secret-pattern scan of sanitized snapshot | no live-key pattern found; synthetic test identifiers only |
| archive-to-audit-tree integrity comparison | 368 original files checked; zero unexpected changes or missing files after restoring generated output |

The first `pip-audit` invocation audited the temporary audit tool environment rather than
the project and is not used as product evidence. It was corrected by auditing
`apps/api/.venv/lib/python3.11/site-packages`, which produced the recorded findings.

The Next.js production build regenerated `apps/web/next-env.d.ts`. That generated change
was restored byte-for-byte to the uploaded snapshot version after the build. The final
integrity comparison found changes only in the six requested audit documents.

### Backend test blockers

The failing tests were:

1. `test_runner_creates_incident_from_real_payment_history`;
2. `test_aggregates_first_outcome_without_late_authorization_rewrite`;
3. `test_failure_then_late_authorization_is_atomic_and_idempotent`.

All stopped at `RuntimeError: Database URL is not configured`. No assertion in their
business behavior ran. A Windows/Docker PostgreSQL rerun is required before closure.

### Live investigator evidence reviewed

Latest supplied report: `.runtime/phase17b-live-final-v3.json`.

- selected model: none;
- truth compatibility: 20%;
- tool selection: 20%;
- citation validity: 30%;
- abstention accuracy: 0%;
- provider failures: 60%;
- malformed output: 0%;
- failed safe: 70%;
- p95 latency: 34,523 ms.

Classification: Phase 17B is `BROKEN` for completion but its safety degradation is useful
evidence. No rerun was made.

### External documentation checks

- Razorpay's September student Buildathon round is complete; future Buildathons were
  publicly indicated but no new date was verified.
- No authoritative public list of every shortlisted or selected student was found. Public
  participant posts report 25,000+ submissions and a final intern cohort drawn from 16
  campuses, but those posts do not establish a complete roster or exact cohort size.
- Google currently lists `gemini-3.8-flash`, `gemini-3.6-flash` and
  `gemini-3.5-flash-lite` as available stable endpoints.
- Google documents `gemini-3.7-flash` as deprecated and transparently routed to
  `gemini-3.8-flash`, so it is not independent failover capacity.

Sources checked on 31 October 2026:

- `https://razorpay.com/buildathon/`
- `https://razorpay.com/ai-builders/`
- `https://in.linkedin.com/in/sumitpremi`
- `https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash`
- `https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash`

### Documentation changes from this audit

- added root `AGENTS.md`;
- added `docs/product/CURRENT-STATE.md`;
- added `docs/product/DECISIONS.md`;
- added `docs/product/ACCEPTANCE-MATRIX.md`;
- added `docs/product/WORK-LOG.md`;
- updated `docs/product/MASTER-EXECUTION-PLAN.md` with the audit reset and ordered gates.

### Remaining limitations

- The uploaded snapshot excluded `.env.example`; its staged diff was not inspected.
- No PostgreSQL/Redis runtime was available in the audit environment.
- No current browser screenshot, accessibility run or end-to-end judge recording was supplied.
- No live Razorpay or Gemini mutation/request was made.
- Documentation was prepared in the audit workspace; owner review is required before
  applying it to the Windows repository.

## 31 October 2026 — Gate 0 preservation checkpoint

The owner accepted the audit as a working baseline, not as a guarantee of correctness,
and authorized Gate 0 only. Application-code modification, commit, deletion and reset
remain prohibited until evidence is shown and the owner explicitly approves the next action.

Read-only preservation was created from the Windows repository:

- branch: `phase-17b/live-investigator-closure`;
- head: `19126456b37d21d1ead659762c5f92916f3a64e1`;
- Git identity: `Dhanush R S <dhanushrs981@gmail.com>`;
- staged paths: 19;
- unstaged paths: 12;
- paths present in both staged and unstaged states: 8;
- untracked paths: 3;
- complete local backup SHA-256:
  `333eb01e641f6ffcba543475cde44f2345e6281a411ddc5823704747b69e9285`;
- shareable report SHA-256:
  `81d412c215e62f3fbc9560c9b07f4e81f55c1ce5391aa4b7d204256e14ad1f2c`.

The complete backup contains separate staged, unstaged and combined binary patches,
exact staged-index files, working-tree files, untracked files, a Git bundle and hashes.
It remains only on the owner's machine and must not be uploaded because it includes the
staged `.env.example` version. The shareable report archive matched its expected hash and
contained no unsafe archive paths.

The `.env.example` diff adds six investigator model/retry/budget variables. No credential
variable name was added. A second local, value-free validation passed for all model-name,
numeric range and retry-order checks; `PotentialSecretVariableCount=0` and `Overall=PASS`.
No environment value was printed or uploaded. `BASE-02` is now `VERIFIED`.

With explicit owner approval, Git created a separate worktree and branch:

- worktree: `D:\NEW VOLUME\INTERNSHIP PREP\RAZORPAY\ReclaimRail-Audit-Reset`;
- branch: `audit/current-state-reset`;
- head: `19126456b37d21d1ead659762c5f92916f3a64e1`;
- changed paths: exactly the six audit documents;
- application paths changed: zero;
- `git diff --check`: passed;
- staged files, commits and pushes: none.

The original mixed Phase 17B worktree remains unchanged and frozen. `BASE-01` and
`BASE-02` are now `VERIFIED`. Gate 0 remains `PARTIAL` only until the owner reviews and
authorizes the documentation commit; application implementation is still unauthorized.

## 8 November 2026 — Gate 0 documentation commit authorization

The owner reviewed the final six-path evidence and authorized exactly one local,
documentation-only commit with message
`docs(audit): establish verified current-state baseline`.

Authorized commit scope:

- `AGENTS.md`;
- `docs/product/ACCEPTANCE-MATRIX.md`;
- `docs/product/CURRENT-STATE.md`;
- `docs/product/DECISIONS.md`;
- `docs/product/MASTER-EXECUTION-PLAN.md`;
- `docs/product/WORK-LOG.md`.

Required identity is `Dhanush R S <dhanushrs981@gmail.com>` for both author and committer.
The commit must contain zero application paths, leave a clean worktree and remain local;
push is not authorized. A successful commit satisfying those checks is the Gate 0
completion artifact. Gate 1 remains unauthorized pending a separate owner decision.

## 8 November 2026 — Gate 1 committed/runtime baseline reproduction

### Authorization and scope

The owner authorized Gate 1 baseline reproduction only. Application behavior changes,
feature implementation, commit, push, reset and deletion were not authorized. Work ran in:

- worktree: `D:\NEW VOLUME\INTERNSHIP PREP\RAZORPAY\ReclaimRail-Audit-Reset`;
- branch: `audit/current-state-reset`;
- head: `8dc1655cfae5ac3507e82d766e81b463cdf617dd`;
- author/committer identity: `Dhanush R S <dhanushrs981@gmail.com>`;
- isolated Compose project: `reclaimrail_gate1`.

The tracked worktree remained clean. Ignored local environment/dependency/runtime files were
created as required for reproduction. No environment value or credential was printed.

### Environment and dependency reproduction

Read-only preflight recorded Git, uv, Python, Node, npm and Docker versions; Docker was
running; required ports and existing original-project containers/volumes were inventoried;
no service, dependency or database was changed during preflight.

Three ignored environment files were prepared with fresh local credentials. Gemini shadow
runtime was disabled. Locked installs completed:

- backend: `uv sync --locked --group dev`, Python 3.11.8;
- frontend: CI-pinned npm 11.13.0 through `npx`, Next.js 16.3.5;
- `uv.lock` SHA-256:
  `00c9d2d556bcfc22d8b85b48f38565a112a97a67608b11f472222624f6b9e639`;
- `package-lock.json` SHA-256:
  `c96187c2a25c02927315727f6cd950ad55f46411ba5b5846a52ea98922794563`;
- both lockfiles unchanged.

The npm install reported 13 known findings across all installed dependencies: 8 moderate,
4 high and 1 critical. No `npm audit fix` or forced upgrade was run because Gate 1 did not
authorize dependency changes.

### Isolated infrastructure and migration evidence

PostgreSQL `17.11-alpine` started healthy at `127.0.0.1:55432`. Redis initially failed to
bind `56379`; Windows excluded the `56300-56399` range. An early diagnostic script also
failed because it rejected an empty line, and its replacement failed due an invalid Docker
format template. Those script failures are retained as evidence.

The port conflict was diagnosed directly with Windows port-exclusion output. Only ignored
environment values were changed to `16379`, and only the failed Gate 1 Redis container was
recreated. Redis then became healthy. Original `reclaimrail` containers and volumes were
not changed.

Fresh Alembic migration from base to the single head completed through
`e7a1c2d3f417`. A PowerShell 5.1 output-capture wrapper incorrectly raised
`NativeCommandError` on Alembic INFO output written to stderr. Direct commands then proved:

- `alembic current`: `e7a1c2d3f417 (head)`, exit 0;
- `alembic heads`: `e7a1c2d3f417 (head)`, exit 0;
- `alembic check`: `No new upgrade operations detected.`, exit 0;
- PostgreSQL connectivity: passed;
- Redis connectivity: passed.

The wrapper failure was tooling noise, not a migration failure. Future Windows commands
must not combine `$ErrorActionPreference = "Stop"` with redirected native stderr when the
tool legitimately logs INFO output there.

### Backend and frontend quality gates

| Gate | Result |
| --- | --- |
| Ruff format | passed; 249 files already formatted |
| Ruff lint | passed |
| strict mypy | passed; 119 source files |
| pytest | `686 passed, 1 skipped in 16.81s`; exit 0 |
| frontend ESLint | passed; exit 0 |
| Next.js production build | passed; exit 0 |

The one skip was
`tests\test_recovery_action_executor_integration.py:57`: known persisted execution-counter
integration race; provider idempotency is covered separately. This remains a recorded
limitation, not an unexplained skip.

The frontend build compiled `/`, `/cases`, `/cases/[caseId]`, `/evaluations`,
`/intelligence`, `/outcomes`, `/payment-lab`, `/reviews`, `/safety-controls` and its two
current API routes. There is no frontend unit or E2E test suite.

### Full controller startup and browser evidence

The first full startup timed out after 120 seconds. Logs showed four provider-facing
workers required a Razorpay key ID and secret. A value-free check proved the frozen original
worktree contained a Test Mode-looking key ID, key secret and webhook secret. The isolated
database still had zero recovery cases, actions, outcomes and approvals.

Only the existing Razorpay Test Mode key ID/secret were copied into the ignored Gate 1
backend environment without printing values. The isolated generated webhook secret was
retained. The tracked controller then reported:

- `ReclaimRail is ready`;
- API readiness: ready;
- 11/11 processes running;
- 8/8 workers healthy with zero consecutive failures;
- controller start exit 0;
- controller status exit 0.

Browser evidence showed the Payment Lab rendered at
`http://127.0.0.1:3000/payment-lab`. This proves a live compiled page and navigation shell,
not the required same-case recovery acceptance.

### Signed webhook and projection evidence

A locally signed controlled synthetic `payment.failed` payload was submitted to the local
webhook service with unique synthetic provider event, payment and order identifiers.

Results:

- first receipt: HTTP 202, `accepted`;
- exact replay: HTTP 200, `duplicate`;
- both receipts returned the same canonical event ID;
- canonical webhook count: one;
- delivery count: two;
- processing status: `processed`;
- payment transition: `unknown -> failed`, `applied`, reason `initialized`;
- transition evidence source: `verified_webhook`.

The evidence proves signature verification, durable idempotency and projection. It does
not prove a provider-emitted Razorpay Test Mode webhook. The payload provenance is
controlled synthetic and must remain labelled that way.

### Failed case gate and P0 reconciliation defect

The repository's existing case service was invoked only after projection. It correctly
refused to create a recovery case with `recovery_not_eligible`. A read-only diagnosis found:

- payment state `failed`, state version 1;
- recovery eligibility false;
- no recovery stop timestamp/reason;
- latest truth `manual_investigation_required`;
- diagnostic sample truth version 127;
- diagnostic sample evidence count 128;
- first two evidence rows: verified webhook failure and merchant-database failure;
- remaining sampled rows: authoritative reconciliation
  `provider.available=false` evidence.

Repository code and logs established `G1-P0-001`:

1. the Payment Lab recovery worker calls `reconcile_payment_truth_batch` whenever the
   Razorpay order provider is configured;
2. manual-investigation candidates are immediately selectable on every poll;
3. unavailable evidence uses a timestamp in `source_reference`, defeating idempotent
   insertion for equivalent failures;
4. every row reruns truth resolution and can append a new snapshot; and
5. the circuit counter is scoped to one batch, so a single repeatedly failing candidate
   never opens a durable circuit across batches.

Final log evidence contained 453 reconciliation batch lines and all 453 reported:

```text
checked=1 projected=0 unavailable=1 persistence_failures=0 circuit_opened=False
```

The typical interval was approximately 1.3 seconds. The earlier webhook command printed
`RazorpayApiCalled=False` because that command itself did not call Razorpay; that statement
was incomplete at system level. The enabled background worker made repeated Test Mode
provider-read attempts. This correction is intentionally retained.

No recovery case, action, approval, outcome, Payment Link or money-moving provider
execution occurred. Gemini shadow remained disabled and no live Gemini call/corpus ran.

### Containment and final state

The full tracked controller was stopped immediately after the amplification was confirmed.
All 11 application processes stopped successfully. PostgreSQL and Redis were left preserved
for audit evidence. Runtime status then reported no ReclaimRail process state, API readiness
unavailable and worker diagnostics unavailable. Git status remained clean.

### Gate 1 decision

Gate 1 is `BROKEN` because mandatory bounded reconciliation and same persisted-case frontend
proof failed. Passed sub-gates remain individually `VERIFIED`; they are not discarded.

No application code, tracked runtime configuration, branch, commit or Git reference was
changed. No commit or push was performed. The recommended next phase is the separately
approved Gate 1A remediation defined in the master plan and acceptance matrix.

## 17 November 2026 — Gate 1 documentation closure preparation

The six audit documents were refreshed from the owner's uploaded documentation-only ZIP.
This preparation records the 8 November evidence and creates the Gate 1A specification.
It does not authorize or implement Gate 1A, change application code, restart services,
alter the preserved database, commit or push. Owner review of the complete six-path diff is
required before applying or committing the documentation refresh.

## 17 November 2026 — Gate 1A bounded reconciliation candidate

### Authorization and repository state

The owner authorized Gate 1A only after the Gate 1 documentation commit. The worktree was:

- `D:\NEW VOLUME\INTERNSHIP PREP\RAZORPAY\ReclaimRail-Audit-Reset`;
- branch `audit/current-state-reset`;
- parent `8703bfbd9a3b36dcf4a1af74a1bb04ea76311f5d`;
- identity `Dhanush R S <dhanushrs981@gmail.com>`;
- 15 changed application/test/frontend paths;
- zero staged files, commits or pushes.

No live Gemini call, live Razorpay verification, provider mutation or money movement was
authorized or performed.

### Changed application/test/frontend paths

1. `apps/api/.env.example`
2. `apps/api/app/core/config.py`
3. `apps/api/app/db/models/__init__.py`
4. `apps/api/app/db/models/payment_truth.py`
5. `apps/api/app/services/payment_truth_reconciliation.py`
6. `apps/api/app/workers/payment_lab_recovery_worker.py`
7. `apps/api/migrations/versions/f8c1b2d3e4a5_add_truth_reconciliation_control.py`
8. `apps/api/tests/test_payment_lab_recovery_worker.py`
9. `apps/api/tests/test_payment_truth_reconciliation.py`
10. `apps/api/tests/test_payment_truth_reconciliation_control_integration.py`
11. `apps/api/tests/test_worker_supervision_config.py`
12. `apps/web/src/app/safety-controls/page.tsx`
13. `apps/web/src/components/operations-page.tsx`
14. `apps/web/src/components/safety-controls-panel.tsx`
15. `apps/web/src/lib/recovery-api.ts`

The candidate adds durable per-attempt reconciliation state, persisted cooldown/backoff,
retry budget, circuit/exhaustion state, stable unavailable-evidence identity, synthetic
provider blocking, restart-safe worker metrics and a Safety Controls representation.

### Deterministic commands and results

The guarded Windows validation ran these commands from `apps/api` or `apps/web` as
applicable:

| Command | Result |
| --- | --- |
| `uv run --frozen alembic upgrade head` | passed |
| `uv run --frozen alembic current` | `f8c1b2d3e4a5 (head)` |
| `uv run --frozen alembic heads` | `f8c1b2d3e4a5 (head)` |
| `uv run --frozen alembic check` | passed; no new upgrade operations |
| `uv run --frozen ruff format --check .` | passed; 251 files already formatted |
| `uv run --frozen ruff check .` | passed |
| `uv run --frozen mypy app` | passed; 119 source files |
| focused Gate 1A pytest selection | `22 passed in 2.55s` |
| `uv run --frozen pytest -q` | `698 passed, 1 skipped in 13.69s` |
| `npm run lint` | passed |
| `npm run build` | passed; Next.js 16.3.5 routes compiled |

The one skip remains the known persisted execution-counter integration race recorded in
Gate 1. No new skip was introduced by Gate 1A.

An earlier focused run produced `21 passed, 1 failed`: the provider-recovery test projected
fresh failed truth but did not restore `recovery_eligible`. The correction added the
provider event entity expected by canonical processing and required the reconciliation
path to confirm processor disposition before reporting projection. The next focused and
complete runs passed. The failed run remains part of the audit trail.

### Controlled runtime evidence

The owner ran:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$env:USERPROFILE\Downloads\ReclaimRail-Gate1A-Runtime-Evidence-20261117\Run-ReclaimRail-Gate1A-Runtime-Evidence.ps1"
```

The final run used a fresh database
`reclaimrail_gate1a_runtime_20261117153137`, isolated Redis logical DB 15, and migrated from
base through `f8c1b2d3e4a5`. It started only the API, web and target Payment Lab recovery
worker. Results:

- API ready and target worker healthy;
- repeated attempt inside the open circuit made zero provider calls;
- circuit scenario evidence/truth counts remained 3/3 before and after the blocked repeat;
- three scheduled unavailable calls opened the persisted circuit;
- worker restart made zero unexpected provider calls;
- synthetic path recorded one block and zero provider calls;
- expired unavailable evidence was superseded by fresh deterministic provider-stub failed
  evidence, restoring `recovery_eligible=true`;
- worker metrics exposed calls, unavailable results, two cooling controls, one open circuit,
  one exhausted control and one synthetic block;
- temporary processes stopped; runtime changed zero application files.

Controlled case `a809f8fc-7b5a-43b4-943f-f6addeb8cc21` rendered ₹3,499 INR, failed state,
open recovery eligibility and no active link. Stored truth was ordered newest first:
version 2 `payment_failed` after version 1 `manual_investigation_required`. The audit chain
was valid.

The first runtime wrapper failed before startup with `ModuleNotFoundError: app` because its
external harness did not set the API import path. After that wrapper was corrected, a
second run failed its evidence assertion because the verifier selected the oldest truth
record instead of the newest. Neither was an application failure; both wrapper failures
and their preserved logs remain recorded. The third run passed.

Final shareable evidence archive:

- file: `ReclaimRail-Gate1A-Runtime-Evidence-20261117-153137-shareable.zip`;
- SHA-256: `1cd41edd8e5929df24f51e211f560ad0703bc2c5a852fe1b39bc80b1f2830027`;
- screenshot commands: `CAPTURE_SAFETY-1024X1400`, `CAPTURE_SAFETY-1440X1800`,
  `CAPTURE_SAFETY-1920X2200`, `CAPTURE_CASE-1440X2200`; all exited 0.

### Frontend evidence review

The Safety Controls page visibly documents that provider reconciliation is bounded and
shows live worker values. Automated browser assertions found all six Gate 1A metrics in the
DOM. Manual inspection found limitations that keep the browser gate `PARTIAL`:

- at 1024px the navigation and right-side policy-table content are clipped;
- at 1920px the first reconciliation columns are legible, while open-circuit, exhausted
  and synthetic-block columns require horizontal scrolling and are not in the static image;
- the 1440px case header clearly shows the same failed ₹3,499 case, but lower evidence cards
  are washed out in the capture;
- no keyboard, focus-order, contrast or automated frontend behavior test was run.

### Decision and remaining limitations

Requirements G1A-01 through G1A-07 are `VERIFIED`. G1A-08 and Gate 1A overall are
`PARTIAL` because the full tracked 11-process controller, clean responsive browser proof
and provider-emitted Test Mode provenance remain absent. No live provider call is required
to prove the already-closed amplification defect; any bounded read-only verification needs
separate owner approval.

The next allowed work is Gate 1A closure only: owner review, responsive evidence correction,
full-controller rerun, exact staged-diff verification and one owner-authorized local commit.
Gate 2, Phase 17B and new feature work remain unauthorized.

## 18 November 2026 — unified roadmap reconciliation draft

### Authorization and scope

The owner supplied `ReclaimRail_Unified_Master_Roadmap_2026-11-17.md` and authorized a
documentation reconciliation without losing existing work or beginning Gate 2, Phase 18
or unrelated implementation. The six audit documents remain authoritative for repository
state. No application behavior, database contents, Git index, commit, branch, remote or
provider state is changed by this reconciliation draft.

### Preflight stop and preservation

The Gate 1A closure runner stopped at its first changed-path guard:

```text
Initial changed-path verification failed. Expected 21, found 22.
```

The runner stopped before installing its two frontend corrections or starting validation.
The guard was not weakened. The additional path remains preserved and is classified
`NEEDS INSPECTION` until exact `git status --short` output identifies it. A read-only
branch/HEAD/identity/status command was requested; no environment value is printed.

### Roadmap conflicts resolved in the draft

1. The proposal's `19 passed, 2 failed` snapshot is superseded by the append-only Gate 1A
   record: intermediate `21 passed, 1 failed`, then focused `22 passed`, full backend
   `698 passed, 1 skipped`.
2. M0–M8 are retained as priority/crosswalk views only. They do not replace the established
   Gate 1A → Gate 2 → Phase 17B → Phases 18–23 order.
3. The F-01 to F-50 catalogue is mapped to existing phases, code/tests and current evidence;
   appearance in the catalogue is not proof that a feature is missing or complete.
4. Stale-approval prevention and durable provider intent/reconciliation remain mandatory
   selection-critical safety requirements.
5. Provider-backed Test Mode, replay and controlled synthetic cohorts remain separate.
6. Account-specific Razorpay capability verification is moved early, but no provider call
   or mutation is authorized by the roadmap integration itself.
7. Submission-critical safety, one provider-backed journey, honest AI evidence and
   reproducibility take priority over optional P1/P2 polish.

### Documentation draft

- adds `docs/product/UNIFIED-MASTER-ROADMAP.md` as `DRAFT — RECONCILED, NOT LOCKED`;
- updates `AGENTS.md` with document authority, read order and `NEEDS INSPECTION`;
- references the unified blueprint from `MASTER-EXECUTION-PLAN.md` without replacing its
  historical requirements or active work order;
- adds the evidence-mapped F-01 to F-50 ledger to `ACCEPTANCE-MATRIX.md`;
- records the stale test snapshot, 22-path blocker and exact Gate 1A remainder in
  `CURRENT-STATE.md`;
- records proposed roadmap decisions separately from locked decisions in `DECISIONS.md`;
- appends this entry without rewriting earlier failures.

The draft is not installed, staged, committed, pushed or locked. Final hashes and an
installation package must wait until the unexpected local path is identified and the
draft is checked against the exact current repository documents.

## 18 November 2026 — exact 22-path inventory and frontend revalidation

The owner supplied the complete read-only Git status for branch
`audit/current-state-reset` at `8703bfbd9a3b36dcf4a1af74a1bb04ea76311f5d`.
The previously unexpected twenty-second path is
`apps/web/src/app/globals.css`. Its diff contains a bounded responsive Safety Controls
containment grid, responsive navigation changes and disabled case-tab entrance animation;
`git diff --check` passed. The worktree contains 16 application/test/frontend paths and
six audit documents, with zero staged paths.

Fresh frontend validation on the exact 22-path worktree reported:

- ESLint exit `0`;
- Next.js 16.3.5 production build exit `0`;
- TypeScript and all recorded application routes compiled;
- Git diff check exit `0`;
- staged count `0`; and
- changed-path count `22`.

This resolves the changed-path identity and frontend compilation questions. Gate 1A
remains `PARTIAL` pending inspected responsive evidence, full tracked-controller evidence,
authority-document finalization and owner-reviewed commit closure. No application file,
Git index entry, commit or remote reference was changed by this documentation update.

### Fresh full-controller reproduction

The owner then created fresh database
`reclaimrail_gate1a_controller_20261118152748`, isolated Redis logical database 14 and
applied every migration from base through `f8c1b2d3e4a5 (head)`. The tracked local
controller started the API, webhook receiver, eight workers and web application: all 11
processes reported running, API readiness was `ready`, and workers reported `8/8 healthy`
with zero consecutive failures. The worktree remained at 22 changed paths with zero staged
files. Live Gemini and Razorpay mutation were not authorized. Gate 1A now remains partial
only for sustained/bounded log confirmation, inspected responsive browser proof,
authority-document finalization and owner-reviewed commit closure.

### Responsive archive inspection

The owner supplied `ReclaimRail-Gate1A-Responsive-Evidence-20261118-153152-shareable.zip`
with SHA-256 `d6437133b1604432f67aaa5cc96bdc9928c2ab1395eb70347ffaf46bea8bebac`.
It contains six valid PNGs at the declared 1024×1400, 1440×1800 and 1920×2200 sizes.
Visual inspection established:

- the new 1024 navigation grid no longer clips the Evidence Lab item;
- Safety Controls renders cleanly at 1440 and 1920;
- Cases empty state is readable without horizontal clipping at all three widths;
- the 1024 Safety Controls policy-rulebook table still clips the rightmost column; and
- the fresh controller database contains zero cases, so these screenshots do not prove
  the populated case-detail washout is fixed.

The earlier controlled-runtime archive was independently rechecked at SHA-256
`1cd41edd8e5929df24f51e211f560ad0703bc2c5a852fe1b39bc80b1f2830027`.
Its deterministic case JSON proves `payment_failed`, recovery eligibility, stable evidence
counts and zero provider calls after restart, but its populated case screenshot visibly
washes out the lower evidence panels. Gate 1A remains `PARTIAL`; no responsive completion
or commit claim is authorized from these archives.

## 18 November 2026 — final Gate 1A runtime and visual evidence

The owner supplied
`ReclaimRail-Gate1A-Runtime-Evidence-20261118-155209-shareable.zip`, SHA-256
`4af876f59b72da82aa330a0848ac9d29ab8c5175b9325802ca6d09ea92987f71`.
The archive contains 27 shareable files: API/worker JSON, the controlled-runtime report,
provider-truthful case JSON, logs and four screenshots. Independent inspection confirmed:

- fresh database `reclaimrail_gate1a_runtime_20261118155209` migrated through
  `f8c1b2d3e4a5`;
- API ready and `payment_lab_recovery` healthy;
- evidence and truth counts remained `3/3` across the blocked repeat;
- repeat inside the open circuit made zero provider calls;
- restart made zero unexpected provider calls;
- persisted cooling count `2`, open circuits `1`, exhausted count `1` and synthetic
  blocks `1` were visible;
- synthetic input made zero provider calls;
- expired unavailable evidence was superseded by deterministic provider `payment_failed`
  truth with recovery eligibility restored;
- case `e3aefb14-8df5-4d93-a803-5750f78429e5` exposed failed/eligible truth and cited
  evidence in the frontend;
- screenshots are valid at Safety Controls 1024×1400, 1440×1800, 1920×2200 and populated
  case 1440×2200;
- manual visual review found the 1024 navigation and rulebook columns readable and the
  populated case evidence fully legible without the earlier animation washout;
- no traceback, critical, unhandled or worker-failed finding appeared in the archive;
- no live Razorpay call, provider mutation or live Gemini call occurred; and
- the runtime changed zero application files, staged zero files, created no commit and
  performed no push.

Together with the previously recorded focused `22 passed`, complete backend `698 passed,
1 skipped`, Ruff/mypy, frontend lint/build, migration/autogenerate checks and fresh full
11-process controller with 8/8 healthy workers, G1A-01 through G1A-08 are `VERIFIED`.
Gate 1A remains administratively `PARTIAL` only until authority-document review and one
owner-authorized local commit. Provider-emitted Test Mode provenance is not deleted: it is
deferred explicitly to the bounded provider-backed journey and remains `PARTIAL` under
Gate 1/F-38.

## 18 November 2026 — unified roadmap approved and documentation installed

The owner approved the reconciled roadmap and authorized documentation-only installation,
with explicit instructions not to stage, commit or push. The guarded installer verified:

- branch `audit/current-state-reset` at
  `8703bfbd9a3b36dcf4a1af74a1bb04ea76311f5d`;
- Git identity `Dhanush R S <dhanushrs981@gmail.com>`;
- all 16 Gate 1A application/test/frontend paths preserved;
- six existing audit documents updated;
- `docs/product/UNIFIED-MASTER-ROADMAP.md` created;
- zero staged files, commits or pushes; and
- no application-code change by the installer.

The resulting worktree has 23 changed paths: 16 application/test/frontend paths and seven
documentation paths. The roadmap is now formally locked through DEC-021–DEC-027. This lock
does not claim that F-01–F-50 are complete; their evidence classifications remain governed
by the acceptance matrix. Gate 1A remains administratively open until the exact staged diff
and required identity are shown and the owner separately authorizes one local commit.

## 18 November 2026 — Gate 1A local commit authorized

The owner explicitly authorized staging and committing exactly the 23 reviewed Gate 1A
paths as one local commit, required identity
`Dhanush R S <dhanushrs981@gmail.com>`, no push, and a mandatory stop after commit
verification. The approved commit message is:

`fix(reconciliation): persist bounded payment truth retries`

The commit contains 16 application/test/frontend paths and seven documentation paths.
Successful pre-commit checks require the parent
`8703bfbd9a3b36dcf4a1af74a1bb04ea76311f5d`, exact file hashes, exact staged paths,
`git diff --cached --check`, required author/committer identity and zero unstaged/untracked
remainder. The resulting commit hash is recorded by Git and the post-commit terminal
evidence rather than embedded in the commit itself. No push is authorized.

## 18 November 2026 — Gate 2 dependency/access-control candidate

The owner authorized Gate 2 implementation on separate branch
`gate2/dependency-access-control` from commit
`1b26642258ed9e5d3c3b4249d8dc2004050276c9`, targeting controlled reviewer-demo access.
The authorization prohibited staging, committing, pushing, merging, deployment and live
Gemini/Razorpay calls. Those prohibitions were preserved.

Implemented scope:

- upgraded and locked the vulnerable Python transitive packages and supported Next.js
  patch line without broad force-upgrades;
- added a fail-closed reviewer token to 10 operational backend reads while retaining
  public liveness/readiness and existing webhook/lab/operator controls;
- added a signed, expiring, HttpOnly, SameSite=Strict reviewer browser session;
- removed reviewer code storage/forwarding from browser state;
- required same-origin requests for Payment Lab and approval mutations;
- added bounded request size and per-client/global in-memory login throttles;
- added the visible access gate and reviewer logout control; and
- updated the local PowerShell controller to authenticate worker diagnostics without
  printing the token.

Validation performed on the exact uncommitted candidate:

| Check | Result |
| --- | --- |
| Backend Ruff format/lint | passed; 227 application/test files formatted and all checks clean |
| Backend strict mypy | passed; 120 source files |
| Reviewer/access focused tests | `52 passed` |
| Non-PostgreSQL backend regression | `703 passed, 16 skipped` |
| PostgreSQL integration | not run in this Linux environment; Docker command unavailable; three integration files remain for Windows |
| Alembic graph | one head, `f8c1b2d3e4a5` |
| Frontend lint | passed |
| Frontend production build | passed on Next.js 16.4.6; access/session routes and Proxy compiled |
| Python runtime audit | zero known vulnerabilities |
| Python complete audit | zero known vulnerabilities |
| npm production audit | zero vulnerabilities |
| npm complete audit | 14 high findings, all one unpatched dev-only `picomatch` advisory chain; no non-breaking fix available |
| HTTP denial/session proof | unauthenticated page `307` to `/access`; unauthenticated API `401`; missing origin `403`; wrong code `401`; valid code `200`; HttpOnly/Strict cookie; authenticated page `200`; mutation without origin `403`; logout `200` |
| Manual browser proof | protected Payment Lab opened only after access; logout visible at 1050px and returned to `/access` |
| Git safety | parent unchanged, zero staged files, zero commits/pushes/merges/deployments |
| Provider use | no Gemini or Razorpay request or mutation |

The complete npm finding is not silently accepted. npm recommends
`npm audit fix --force`, which would install a breaking `eslint-config-next@14.2.35`
downgrade; that command was not run. Gate 2 remains `PARTIAL` pending owner disposition of
the dev-only advisory and an exact Windows/PostgreSQL integration, migration/controller
smoke and final audit rerun. No Phase 17B work began.

## 18 November 2026 — Gate 2 final Windows/PostgreSQL validation

### Authorization and preserved boundary

The owner authorized final Gate 2 Windows/PostgreSQL validation only. Staging, committing,
pushing, merging, deployment, Phase 17B and live Gemini/Razorpay calls remained prohibited.
The exact branch was `gate2/dependency-access-control` at parent
`1b26642258ed9e5d3c3b4249d8dc2004050276c9`, with required identity
`Dhanush R S <dhanushrs981@gmail.com>`, 46 approved changed paths and zero staged files.

### Deterministic and security results

The first complete Windows run validated the expensive gates before its controller wrapper
was interrupted:

| Check | Final result |
| --- | --- |
| PostgreSQL-focused integration | `3 passed` |
| Complete backend suite | `721 passed, 1 skipped` |
| Ruff format/lint | passed |
| Strict mypy | passed for 120 source files |
| Frontend lint/build | passed; Next.js access/session routes and Proxy compiled |
| Python runtime audit | zero known vulnerabilities |
| Python complete audit | zero known vulnerabilities |
| npm production audit | zero vulnerabilities |
| npm complete audit | one unpatched dev-only `picomatch` advisory represented as 14 transitive high findings |

The owner approved the recommended bounded disposition in `DEC-029`: accept the advisory
only for the lint/build development chain while production/runtime audits remain clean; do
not run the breaking `npm audit fix --force`; reassess when a compatible upstream fix is
available and before hosted/public deployment or Phase 21 closure.

### Validation-harness failures retained honestly

The application did not cause the interrupted validation attempts:

1. the initial wrapper used Windows `Start-Process -Wait`, which waited on the long-running
   controller process tree after successful startup;
2. the first continuation removed process-tree waiting but redirected output through pipes
   inherited by the long-running children, so the output reader did not complete;
3. the next attempt correctly returned from the controller command but detected tracked
   processes left by the interrupted continuation and failed closed rather than starting
   duplicates; and
4. after an explicit controller stop, the corrected continuation inherited console output,
   reused the already validated expensive evidence and completed the runtime gate.

Each interrupted attempt restored environment files. Tracked application paths, the Git
index, commits and remotes were unchanged. These were harness defects and are not counted
as passing application evidence.

### Final controlled runtime evidence

The successful continuation used fresh database
`reclaimrail_gate2_runtime_resume_20261118191824` and isolated Redis logical database 11.
Base-to-`f8c1b2d3e4a5` migration passed. The database contained zero payment-attempt,
recovery-case or recovery-action provider-work candidates before controller start.

The complete local controller then started the API, webhook server, web application and all
eight supervised workers. API readiness passed and workers were 8/8 healthy. Runtime HTTP
assertions passed for:

- public `/health/live` and `/health/ready`;
- unauthenticated denial and authenticated access for worker diagnostics;
- unauthenticated Payment Lab redirect to the access gate;
- unauthenticated frontend API denial;
- reviewer-code exchange for a signed `HttpOnly`, `SameSite=Strict` session;
- authenticated Payment Lab access; and
- reviewer logout.

Recent runtime logs contained zero `api.razorpay.com` or Gemini provider-network findings
and zero traceback/critical/unhandled/worker-failed findings. No Razorpay mutation, live
Razorpay request or live Gemini request was made. The controller stopped all 11 processes.
Environment values were not printed.

Final evidence archive:

- path:
  `D:\NEW VOLUME\INTERNSHIP PREP\RAZORPAY\ReclaimRail-Gate2-Runtime-Continuation-20261118-191824-shareable.zip`;
- SHA-256:
  `fea6daa02efa9cb202a5906b9f463e002caab4d1353b26d698a100b0462227e7`.

### Gate decision and next permitted action

G2-01 through G2-10 are technically `VERIFIED` for the controlled single-merchant reviewer
scope. Hosted identity/tenant enforcement, durable distributed abuse controls and public
proxy validation remain later deployment/Phase 21 requirements and were not silently
claimed or removed.

The 46-path candidate remains uncommitted and the overall work order remains `PARTIAL`
until the owner reviews this documentation reconciliation and separately authorizes the
exact local commit. Zero files were staged; zero commits, pushes, merges or deployments
were performed. Phase 17B did not begin.

## 18 November 2026 — Gate 2 closure documentation reconciliation

The owner authorized documentation reconciliation only after reviewing the final validation
output and shareable archive. This update records `DEC-029` and `DEC-030`, refreshes Gate 2
acceptance rows and preserves the distinction between technical verification and an
uncommitted branch. It modifies only the six authority documents already present in the
46-path candidate. It does not stage, commit, push, merge, deploy or begin Phase 17B.

Next action: present the exact six-document diff and full 46-path status for owner review.
Only a later explicit authorization may stage and commit Gate 2.

## 19 November 2026 — Gate 2 commit and remote closure verified

The owner separately authorized and completed the Gate 2 commit and push after the
pre-commit documentation review. Repository evidence records:

- authoritative branch: `gate2/dependency-access-control`;
- verified closure commit:
  `652e440495ff0d3a9b8c07baa65a24ae2ed2f023`;
- parent: `1b26642258ed9e5d3c3b4249d8dc2004050276c9`;
- commit message: `fix(security): add controlled reviewer demo access`;
- author and committer: `Dhanush R S <dhanushrs981@gmail.com>`;
- committed paths: exactly 46, comprising 40 application/test/configuration paths and the
  six authority documents;
- post-commit and post-push worktree: clean;
- push: successful, without force;
- remote verification: local and remote commit hashes matched, with the branch zero ahead
  and zero behind;
- upstream: tracking configured for `origin/gate2/dependency-access-control`;
- pull request, merge and deployment: none; and
- Phase 17B activity: none.

Gate 2 is therefore `VERIFIED` and `CLOSED`. The bounded `picomatch` disposition in
`DEC-029` remains in force and expires before hosted/public deployment or Phase 21 closure.
This post-commit documentation closure changes only the six authority documents. It does
not modify application behavior, rerun accepted Gate 2 evidence, call Gemini or Razorpay,
or authorize Phase 17B. The next possible work order is Phase 17B read-only diagnosis, but
it requires a separate owner decision after this exact documentation diff is reviewed,
committed and pushed through separate approvals.

## 20 November 2026 — Phase 17B configured-model preflight and corpus-contract remediation

The owner authorized bounded Phase 17B Gemini diagnostics. The first two explicit
`gemini-3.8-flash` preflights returned sanitized `503 UNAVAILABLE` evidence; a replacement
key did not alter that provider-boundary result. The owner then directed the configured
`gemini-3.6-flash` route. Its single Generate Content preflight passed with `minimal`
thinking: one SDK attempt, zero retries, 512 maximum output tokens, 120-second timeout,
automatic function execution and continuation disabled, and a forced read-only
`get_truth_snapshot` selection. The returned function was never executed. No Razorpay call
occurred. Ignored local report:
`.runtime/phase17b/preflight-gemini-3.6-flash-generate-content-configured-20261120.json`.

The owner next authorized exactly one frozen v1 corpus pass with `gemini-3.6-flash`,
`minimal` thinking and a 90-request ceiling. A direct-file launch stopped locally before
Gemini because the runner did not add the API root to `sys.path`; module-mode invocation
then performed the one authorized run. It made ten provider requests, one for each scenario,
and stored ignored sanitized evidence at
`.runtime/phase17b/benchmark-gemini-3.6-flash-corpus-v1-20261120.json`. Thresholds failed:
truth-compatible/tool-selection/citation rates were 0%, provider-failure rate was 100%, and
the report recorded six provider rejections plus two quota-exhausted scenarios without raw
provider text, prompts or secrets.

Deterministic analysis found the candidate corpus contract defect: v1 case IDs such as
`case-01` cannot satisfy the UUID-only read-only tool schema; the preflight used a valid
UUID and passed. v1 and its checksum/report remain unchanged as failure evidence. The
candidate now adds frozen `corpus-v2.json` with UUID case IDs, a matching checksum, local
UUID validation before a provider call, corpus-ID propagation, safe per-scenario provider
diagnostics and a direct-script bootstrap fix. No live v2 run was made.

Focused local validation after the remediation:

| Check | Result |
| --- | --- |
| Ruff format/check | passed |
| Strict mypy, Phase 17B modules | passed; 3 source files |
| Focused Phase 17B deterministic suite | `81 passed in 2.56s` |
| Direct runner bootstrap (`--help`) | passed; no network call |

One separately authorized `gemini-3.6-flash` v2 corpus run then completed within its
90-request ceiling. It made ten calls, one per scenario, and failed before tool selection:
eight sanitized `400 INVALID_ARGUMENT` provider rejections and two `429 RESOURCE_EXHAUSTED`
quota failures. Truth-compatible, required-tool-selection and citation rates were all 0%.
The ignored evidence is
`.runtime/phase17b/benchmark-gemini-3.6-flash-corpus-v2-20261120.json`. The UUID corpus
repair was necessary but did not resolve the full multi-function request contract.

Phase 17B remains `BROKEN`. Do not rerun either corpus. The next work is an offline,
deterministic reduction of the full Gemini request shape and tests for the accepted shape;
any subsequent provider request requires a separate owner authorization. No staging, commit,
push, merge, deployment or Razorpay call occurred.

The offline remediation now reduces every Gemini function declaration to the portable schema
subset `type`, `properties`, `required`, `items` and `enum`, stripping Pydantic-only
presentation/validation metadata while retaining backend UUID and strict argument checks.
Focused Ruff format/check, strict mypy and the Phase 17B deterministic selection pass with
`82 passed in 2.73s`. No provider call followed this correction. The next provider gate is
one separately authorized full-declaration preflight using a valid UUID—not another corpus.

That full-declaration preflight subsequently made exactly one Generate Content request with
all eleven read-only tools and two terminal response contracts. It executed no function and
made no Razorpay call, but timed out at 120.859 seconds without a usable model response.
Ignored sanitized evidence:
`.runtime/phase17b/preflight-gemini-3.6-flash-full-declarations-v2-20261120.json`.
No retry is authorized. The next work is offline request-shape and latency reduction before
any further provider request.

## 21 November 2026 — Phase 17B Groq external-blocker hardening

The owner-authorized Groq corpus-v2 run stopped fail-closed after `3` starts, `2` responses
and `1` indeterminate transport request; retries were `0`. The preserved checkpoint is
`.runtime/phase17b/.groq-corpus-v2-20261121-authorized.checkpoint.json` with SHA-256
`38677f99f60ce24be419b9dcf479dd36b543deff9ba592b6afd90c959eda75de`. No final report,
selection claim or corpus rerun is authorized. Live budget is `26/150`.

The benchmark checkpoint now persists only sanitized request-boundary receipts before an SDK
call and after a response, exception, scenario and terminal transition. Receipts contain
timestamps, configured timeout, elapsed time, reconciled counters, safe failure boundary and
classification, plus allowlisted token/quota metadata; they never retain prompts, observations,
raw responses, headers, opaque IDs, authorization data or secrets. Phase 17B remains `PARTIAL`.

Draft owner decision (not assumed): authorize Phase 18 deterministic implementation while
retaining Phase 17B as a release/submission blocker until a separately authorized live model
selection run completes with its locked thresholds.

The owner subsequently approved that bounded Phase 18 decision in `DEC-032`. It authorizes no
Phase 18 implementation yet: the current task is limited to presenting the exact Phase 17B
partial-checkpoint commit scope for separate path/message approval.

## 21 November 2026 — Phase 17B changed-condition Groq revalidation reconciliation

The owner authorized one changed-condition corpus revalidation after more than four hours,
cleared rolling provider windows, an operational public provider status and hardened
per-request receipts. Preflight passed and the focused wrapper/governor suite reported
`15 passed`. The maximum schedule was 31 request starts with zero retries.

The revalidation used `groq / openai/gpt-oss-120b` and stopped fail-closed without creating
a final report. It completed 3 scenarios and recorded 15 request starts, 14 responses, 1
indeterminate request, 15 SDK attempts, 0 retries and 0 application-tool executions. Confirmed
usage was 32,746 input tokens and 2,072 output tokens; the last confirmed
`request_remaining` was 986.

The preserved checkpoint is
`.runtime/phase17b/.groq-corpus-v2-20261121-revalidation.checkpoint.json`, size 5,124 bytes,
SHA-256 `ce227ad68b163d51705f19bc05639a6ebd9721fe4123a194d10f393efe527d28`.
Request 15 was governor-admitted and failed at `provider_boundary` after 1,375 ms against a
configured 60.0-second timeout. Its sanitized classification is `provider_rejected`. The
checkpoint retains no HTTP status, provider code, provider failure kind, timeout result or
quota-rejection field. The 1,375 ms interval does not prove timeout expiration, and the
evidence does not prove HTTP 400, 429 or 5xx, quota rejection, transport loss or model-quality
failure. The exact provider cause, full-corpus thresholds and model-selection result are
unavailable.

Budget accounting is `23/150` before the first attempt, plus 3 starts to `26/150`, plus 15
revalidation starts to the current `41/150`. One owner-authorized changed-condition corpus
revalidation was executed. No additional execution or retry occurred after it. No further
unchanged-condition corpus execution is authorized. A future revalidation requires materially
changed conditions, a versioned evaluation plan and separate owner authorization.

Phase 17B remains `PARTIAL`. Its implementation, successful controlled canary, offline corpus
validation and PostgreSQL-backed validation remain valid, while the live model-selection gate
remains unsatisfied and blocks release/submission. Groq is neither selected nor rejected on
model quality; no production/model-selection claim exists and no Gemini fallback is authorized.
`DEC-032` continues to authorize deterministic Phase 18 work under this external blocker;
Phase 18 has not begun and Phase 19 is not authorized. `DEC-033` records the durable freeze.

This reconciliation changed authority documents only. It made no provider, application-tool,
database, Razorpay or Gemini call and did not run a corpus or canary. No application code,
runtime artifact, Git index, commit, remote, pull request, merge or deployment was changed.

## 21 November 2026 — Phase 17B request-15 offline diagnosis candidate

The owner authorized offline request-15 diagnosis and a bounded code fix if evidence established
a defect. No provider, corpus, canary, application-tool or PostgreSQL evidence call was
authorized or made. The frozen corpus, checksum, prompts, fixtures, thresholds, credentials,
runtime evidence and `41/150` live budget remain unchanged.

The retained checkpoint contains completed results for `p17b-01` through `p17b-03`. Receipt
token resets show requests 13–15 are the in-progress `p17b-04` conversation, making request 15
turn 3. This differs from the ideal 31-request mocked schedule, where ordinal 15 would be
`p17b-05` turn 3, because the live model used four requests in each of the first three
scenarios. The checkpoint does not retain the two prior tool names, so they cannot be claimed
as actual provider behavior.

Offline reconstruction proved the turn-3 adapter shape is internally valid: roles are
`system,user,assistant,tool,assistant,tool`; each tool result correlates to its immediately
preceding assistant call; parallel tool calls are disabled; choice is the generic `required`
mode; all 11 read-only plus 2 terminal declarations remain available; and schemas exclude
non-portable presentation/reference fields. The adapter maps malformed responses, timeouts,
request transport errors, access denial, quota exhaustion, 5xx and unknown exceptions to
different failure kinds. The preserved `provider_rejected` value therefore proves only the
sanitized adapter rejection class. Because the old receipt discarded typed status/reason
fields, it does not establish the exact HTTP status, provider cause, quota, timeout, transport
loss or model-quality outcome.

The bounded candidate adds only safe frozen scenario/turn coordinates and typed allowlisted
provider status/reason/rate-limit fields to future failure receipts. It never persists prompt,
evidence, response body, arbitrary provider status text, headers, credentials or opaque tool
call IDs. Regression coverage reconstructs the third-turn wire shape and proves private
content remains absent from checkpoints.

Validation:

- focused pre-change mocked suite: `53 passed`;
- focused post-change mocked suite: `55 passed`;
- Ruff format check: 279 files formatted;
- Ruff lint: passed;
- strict mypy: passed for 130 source files; and
- complete backend attempt: `848 passed, 1 skipped, 18 failed, 4 errors`; every failure/error
  was a PostgreSQL integration path receiving `ConnectionRefusedError` from the configured
  but unavailable database endpoint. No non-database regression was observed.

Phase 17B remains `PARTIAL`; offline diagnostics cannot complete the live model-selection gate.
A future separately authorized changed-condition live verification would be required to capture
the new typed receipt fields and complete the frozen corpus. This candidate is uncommitted and
unstaged; no Phase 18 work began.

### PostgreSQL-backed validation continuation

The earlier complete-suite attempt above used the stale configured endpoint and is preserved as
failed evidence. A later owner-authorized continuation inspected the existing isolated container
`reclaimrail_phase17b_validation-postgres-1` without printing credentials. It was already
running healthy as PostgreSQL 17.11 with the required `127.0.0.1:55433` binding, so no container,
volume, password or configuration was created or changed. Its established credentials were used
only through process-local environment state.

Results:

- TCP `SELECT 1`: passed;
- Alembic `current`: `b17b9c3d4e5f (head)`, exit 0;
- Alembic `heads`: `b17b9c3d4e5f (head)`, exit 0;
- Alembic `check`: no new upgrade operations, exit 0;
- Ruff format check: 279 files formatted, exit 0;
- Ruff lint: passed, exit 0;
- strict mypy: 130 source files, exit 0;
- focused Groq/benchmark suite after adding the no-HTTP-response regression: `56 passed`;
- complete backend suite: `871 passed, 1 skipped`, exit 0; and
- final durable JUnit:
  `.runtime/phase17b/phase17b-request15-offline-validation-final-20261121.junit.xml`,
  121,309 bytes, SHA-256
  `e2e0839c6df8814302378e413fb11fca3ce4356e06ce93efc5165c81ecb01c64`.

The one skip remains the recorded execution-counter integration race. The diagnostic review now
covers both a provider exception with no HTTP response and a typed HTTP rejection. Future
receipts retain only validated scenario ID/turn, typed allowlisted HTTP status/reason/rate-limit
metadata and the pre-existing safe counters. They never retain raw exception text, prompts,
evidence, headers, response bodies, opaque IDs or secrets.

This validation made no provider, corpus, canary, Razorpay or application-tool call. The frozen
corpus/checksum, model, prompts, fixtures, thresholds, provider ordering, safety boundaries,
credentials, runtime evidence and `41/150` live budget remain unchanged. Phase 17B is still
`PARTIAL` and blocks release/submission. `DEC-032` still permits Phase 18, but the owner chose
to continue Phase 17B; Phase 18 did not begin. No full corpus run is authorized. Any next live
action requires a separately reviewed, narrowly bounded diagnostic plan.

## 21 November 2026 — Phase 17B p17b-04 diagnostic wrapper offline implementation

### Authorization and repository preflight

The owner authorized only the evaluation-only `p17b-04` diagnostic wrapper, mocked tests and
three authority-document updates. Live execution was explicitly prohibited. Before editing,
all required authority documents were read in order. Repository evidence matched exactly:

- root: `D:\NEW VOLUME\INTERNSHIP PREP\RAZORPAY\ReclaimRail-Gate2`;
- branch: `phase17b/investigator-closure`;
- HEAD: `218b70da3c6c4716bcb4c5d93d675316a6d0d257`;
- worktree, staged paths and untracked paths: clean/zero;
- Git identity: `Dhanush R S <dhanushrs981@gmail.com>`.

### Implemented scope

Only these runtime/test paths were added:

1. `apps/api/scripts/run_phase17b_groq_p17b04_diagnostic.py`;
2. `apps/api/tests/test_phase17b_groq_p17b04_diagnostic.py`.

The wrapper hard-locks corpus-v2 SHA-256
`814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de`, scenario
`p17b-04`, provider/model `groq/openai/gpt-oss-120b`, starting-budget acknowledgement
`41/150`, three maximum request starts, zero retries and no failover. It uses the existing
`run_frozen_scenario` engine from turn 1, allowing model-selected tools to choose only their
matching frozen observations. It does not force tool names, arguments, observations or opaque
IDs and does not import an application-tool executor.

The engine `max_requests=3` and an independent pre-transport wrapper both enforce the ceiling.
Provider/governor failures, malformed output and invalid/repeated/wrong-argument turns stop
fail-closed. An otherwise valid third non-terminal tool turn records
`incomplete_request_ceiling`, not a corpus verdict. Final/checkpoint artifacts are new-only,
ignored `.runtime/phase17b` JSON paths and contain sanitized coordinates, counters/timings and
typed allowlisted provider diagnostics. They explicitly record `corpus_verdict=not_evaluated`
and `model_selection=not_evaluated`.

### Offline commands and exact results

The first formatter invocation inside the restricted sandbox could not open the existing user
uv cache (`Access is denied`). The same offline command was rerun with access to that existing
cache and formatted one new file. No dependency download or network/provider request occurred.

| Command | Result |
| --- | --- |
| `uv run --frozen ruff format scripts/run_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_p17b04_diagnostic.py` | passed; `1 file reformatted, 1 file left unchanged` |
| `uv run --frozen ruff check scripts/run_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_p17b04_diagnostic.py` | initial run found one unused `json` import; import removed |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py` | initial run `14 passed, 2 failed`; failures were test-fixture defects (mutable observation-list capture and schema-invalid empty-evidence terminal), not runtime/provider failures |
| same isolated new-test command after fixture correction | `16 passed in 1.62s` |
| `uv run --frozen ruff format --check app scripts tests` | passed; `253 files already formatted` |
| `uv run --frozen ruff check app scripts tests` | passed; all checks passed |
| `uv run --frozen mypy app scripts/run_phase17b_groq_p17b04_diagnostic.py` | passed; no issues in 130 source files |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_benchmark_wrapper.py tests/test_phase17b_groq_governor.py tests/test_groq_evidence_investigator.py tests/test_phase17b_benchmark.py` | passed; `67 passed in 7.60s` |

The mocked coverage proves exact preflight acknowledgements before credential loading, locked
scenario/checksum, new-only destinations, natural observation counts `0 -> 1 -> 2`,
model-selected frozen lookup, early terminal handling, the absolute three-start ceiling,
failure on each possible start without retry, governor refusal before transport, malformed
output, unsafe tools/arguments, artifact redaction, prohibited-import absence and no quality
selection claim.

### Provider and phase result

Groq, Gemini, Razorpay, PostgreSQL, workers, application-tool executors, the corpus and canary
were not called or run. No provider credential was loaded by validation and no `.runtime`
artifact was created. The live budget remains `41/150`. Historical request 15 remains actual
`p17b-04` turn 3, but its old receipt still lacks the provider-generated prior tool names,
opaque IDs and typed cause; the exact rejection cause remains unknown. This wrapper cannot
recover that history and was not presented as doing so.

Phase 17B remains `PARTIAL`, Groq remains neither selected nor rejected on quality, and release/
submission remains blocked. Running this wrapper requires a separate owner authorization; the
`41/150` acknowledgement is only a guard. No staging, commit, push, branch switch, deployment or
Phase 18 work occurred.

## 21 November 2026 — p17b-04 unsafe-terminal offline correction

A read-only review of the five-path diagnostic candidate found one unsafe success signal. The
authoritative frozen-scenario engine records citation validity and forbidden-summary safety,
but the wrapper classified every schema-valid terminal turn as `terminal_response` and returned
success before checking those booleans. An early complete turn could therefore cite unseen
evidence, or a fully observed turn could contain a forbidden recovery recommendation, while the
wrapper still exited zero. No provider or application path had been run with that candidate.

The wrapper now classifies a terminal with invalid citations or `failed_safe=false` as
`unsafe_terminal_response`, persists the engine's typed `citations_valid` boolean, writes no
prompt/summary/evidence ID/tool name and returns nonzero. `corpus_verdict` and `model_selection`
remain `not_evaluated`. The safe early-terminal test now uses an evidence-free abstention rather
than unseen citations. New mocked tests prove unseen-citation and forbidden-summary terminals
fail closed with sanitized final/checkpoint artifacts, and cancellation after request start
leaves only a sanitized checkpoint. The prior ceiling, governor, provider-failure, malformed,
unsafe-tool/argument, redaction and no-selection checks remain in the focused suite.

Offline results:

| Command | Result |
| --- | --- |
| `uv run --frozen ruff format scripts/run_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_p17b04_diagnostic.py` | passed; `1 file reformatted, 1 file left unchanged` |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py` | passed; `19 passed in 1.84s` |
| `uv run --frozen ruff format --check app scripts tests` | passed; `253 files already formatted` |
| first `uv run --frozen ruff check app scripts tests` | failed with one import-order finding after adding `asyncio`; import order corrected |
| final `uv run --frozen ruff check app scripts tests` | passed; all checks passed |
| `uv run --frozen mypy app scripts/run_phase17b_groq_p17b04_diagnostic.py` | passed; no issues in 130 source files |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_benchmark_wrapper.py tests/test_phase17b_groq_governor.py tests/test_groq_evidence_investigator.py tests/test_phase17b_benchmark.py` | passed; `70 passed in 7.65s` |
| `git diff --check` | passed; exit 0 |

No diagnostic, Groq, Gemini, Razorpay, PostgreSQL, worker, corpus, canary or application-tool
execution occurred. No provider credential was loaded and no `.runtime` artifact was created.
Phase 17B remains `PARTIAL`; Groq remains neither selected nor rejected on quality; the exact
historical request-15 rejection cause remains unknown; and the live budget remains `41/150`.

## 21 November 2026 — p17b-04 diagnostic closed; full-corpus preparation only

The owner closed the p17b-04 diagnostic after the v2 run: Groq was healthy, six of six
requests received responses, no provider error occurred, and no validator rejected a response.
The six model-selected tools were `get_truth_snapshot`, `get_internal_payment`,
`get_merchant_policy_summary`, `get_payment_link_status`, `get_provider_payment` and
`get_recovery_history`. The result stopped at the diagnostic six-start ceiling before a
terminal answer. The engine's existing `malformed_output=true` field therefore represented
request-budget exhaustion, not malformed provider output. No quality or model-selection claim
is made. Budget is `50/150`; Phase 17B remains `PARTIAL`.

### Full governed corpus preparation — not run

- Frozen corpus scenarios: `10`.
- Authoritative engine maximum turns per scenario: `9` (`run_frozen_scenario` defaults to
  `max_requests=9` and loops while `request_count < max_requests`).
- Worst-case starts: `10 x 9 = 90`.
- The diagnostic ceiling of `6` was wrapper-specific and was not the engine limit.
- Remaining live budget after the closed diagnostic: `100`; the 90-start worst case fits with
  10 starts of headroom. No budget increase is proposed unless a revised plan adds requests.
- Existing full runner hard ceiling: `31`, which is insufficient for a complete worst-case
  corpus and currently stops the whole run on provider/malformed failure.

The full runner does not yet use the DEC-034 retention seam: it constructs the older plain
`MeteredProvider`, while the retention-aware implementation is currently in the p17b-04
diagnostic wrapper. Before any corpus run, an offline change is required to share the bounded
scrubber/receipt capture with the full runner and add tests proving every turn retains only
DEC-034 fields. The corpus must not run until that change passes offline gates.

Proposed owner decision: a rejected or indeterminate scenario is recorded as a failed
case-level result with complete sanitized diagnostics, then the governed run continues to the
next scenario. Aggregate denominators must report all ten scenarios, including failed and
incomplete cases; no failed case may be silently dropped or converted into a quality pass.

Planned run contract after approval and offline correction:

- corpus/checksum: corpus-v2 / `814ccaab7c8f09b3ef70f41ab7838384ccb1c7a777d0c8070d2ec0b6337839de`;
- model: Groq `openai/gpt-oss-120b` only;
- request ceiling: 90 starts worst case, with no retries/failover;
- output/checkpoint: new files under ignored `.runtime/phase17b`;
- lease: one exclusive run lease, new-only destination checks inside the lease, stale lease
  fails closed;
- Gemini, Razorpay, application tools, PostgreSQL and workers: not used.

The three commits `0ba09c0`, `29b95c3` and `218b70d` are not local-only: each is present on
`origin/phase17b/investigator-closure`, and the branch tracks that remote at the same HEAD.
No push occurred during this preparation.

## 21 November 2026 — DEC-034 diagnostic retention and owner-authorized p17b-04 run

### Preserved prior artifact

Before editing, the prior report and checkpoint were printed and preserved unchanged. They
contained three responses and `malformed_output=true`, but no per-turn tool, call-ID, HTTP,
provider-reason or validator fields. The missing fields could not be reconstructed.

### Offline implementation

The owner authorized `DEC-034`: synthetic frozen-corpus diagnostics may retain only typed,
allowlisted HTTP status, provider error code/type, a first-300-character scrubbed error message,
tool name, arguments limited to 500 scrubbed characters, call ID, finish reason, turn type and a
local validation-failure reason. Headers, bearer/API keys, credentials, raw payloads, prompts,
customer data and unsanitized provider text remain forbidden.

The essential adapter change is limited to an in-memory `last_diagnostic_details` seam containing
the already-validated function call before conversation cleanup. The wrapper scrubs bearer/key-
like values and header names, bounds fields, and persists only those allowlisted values. It does
not alter tool execution, truth, policy, approval, persistence or provider ordering.

Offline validation after the retention change:

| Command | Result |
| --- | --- |
| Ruff format on adapter/wrapper/tests | `3 files left unchanged` |
| Ruff lint on adapter/wrapper/tests | `All checks passed!` |
| strict mypy (`app` plus wrapper) | `Success: no issues found in 130 source files` |
| focused Phase 17B suite | `73 passed in 8.06s` |

The first retention test correctly failed because the scrubber left the literal `x-api-key`
header name in the message; the header-name scrub was added and the final suite passed.

### Owner-authorized live run

The first invocation with the new v2 output path stopped before credentials because the wrapper
still required the historical `41/150` acknowledgement. No provider request occurred. The guard
was corrected to the current budget `44/150`, offline validation was rerun (`73 passed in 8.06s`),
and the one authorized live run executed exactly six starts with Groq
`openai/gpt-oss-120b`, 60-second timeout, zero retries and no failover.

New ignored artifacts:

- `.runtime/phase17b/groq-p17b-04-diagnostic-20261121-owner-v2.json`
- `.runtime/phase17b/.groq-p17b-04-diagnostic-20261121-owner-v2.checkpoint.json`

Per-turn retained details:

| Turn | Tool | Arguments | Call ID | Finish | Result |
| ---: | --- | --- | --- | --- | --- |
| 1 | `get_truth_snapshot` | `{"case_id":"00000000-0000-4000-8000-000000000004"}` | `fc_b30eab10-35f9-45dd-a920-67b521a0b991` | `tool_calls` | response, 1156 ms, 2134/73 tokens, request remaining 999 |
| 2 | `get_internal_payment` | same case ID | `fc_5cf4390b-3cc5-4a14-a796-cc986009df88` | `tool_calls` | response, 985 ms, 2218/88 tokens, request remaining 998 |
| 3 | `get_merchant_policy_summary` | same case ID | `fc_3f8cbf7a-133d-4fc9-ab91-f96084e642ff` | `tool_calls` | response, 985 ms, 2292/116 tokens, request remaining 997 |
| 4 | `get_payment_link_status` | same case ID | `fc_4e04b353-d825-428e-9b13-be10f95bf4e6` | `tool_calls` | response, 1250 ms, 2372/94 tokens, request remaining 996 |
| 5 | `get_provider_payment` | same case ID | `fc_01315bd5-15be-4ba1-b51e-e54af1085422` | `tool_calls` | response, 1094 ms, 2449/95 tokens, request remaining 995 |
| 6 | `get_recovery_history` | same case ID | `fc_987b5d95-67c3-439f-b12f-e39e6ca7d631` | `tool_calls` | response, 937 ms, 2523/86 tokens, request remaining 994 |

No HTTP status, provider error code/type, scrubbed error message or validator rejection was
retained because no provider error occurred. The run stopped at the six-start ceiling. The
engine labelled the result `incomplete_request_ceiling`, `malformed_output=true`,
`citations_valid=false`, `failed_safe=true`; this is the existing budget-exhaustion encoding,
not evidence that a provider response was malformed. `corpus_verdict` and `model_selection`
remain `not_evaluated`. Budget accounting is now `50/150`. No corpus, Gemini, Razorpay,
application-tool, PostgreSQL or worker call occurred. No staging, commit or push occurred.

## 21 November 2026 — p17b-04 concurrent-invocation offline safeguard

The five-path candidate was reviewed again from its complete Python contents and exact
authority-document diff. Existing mocked evidence already proved that `MeteredProvider`
increments `request_starts` and persists a receipt before awaiting transport, so successful,
failed and cancelled requests all spend a start. It also proved the per-run three-start cap,
non-terminal third-turn incomplete state, invalid-citation/forbidden-summary non-success,
malformed and unknown/repeated/wrong-argument turns, and adapter rejection of multiple tool
calls.

The review found one remaining concrete failure path: the counter and cap belonged to one
`MeteredProvider`, so simultaneous wrapper processes could each pass preflight and start up to
three requests. Two same-path invocations could also both observe absent output/checkpoint
destinations before either wrote its first receipt. This was not covered by the earlier tests.

The wrapper now creates one exclusive process-visible lease file under ignored
`.runtime/phase17b` before loading credentials or constructing transport. A concurrent or stale
lease raises a closed diagnostic error and remains available for operator inspection. After
acquiring the lease, the wrapper rechecks that output and checkpoint are still absent. The
lease is released in a `finally` path; cancellation retains the sanitized checkpoint and removes
only the lease. Tests prove a nested concurrent attempt cannot enter or overwrite sentinel
artifacts, an active/stale lease blocks before credential loading without deleting the lease,
and cancellation releases the lease after counting the indeterminate request.

Offline results:

| Command | Result |
| --- | --- |
| `uv run --frozen ruff format scripts/run_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_p17b04_diagnostic.py` | passed; `1 file reformatted, 1 file left unchanged`; final repeat left both unchanged |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py` | passed; `21 passed in 1.93s` |
| first `uv run --frozen ruff check app scripts tests` | failed with two test-only `SIM117` context-manager style findings; corrected without behavior change |
| final `uv run --frozen ruff format --check app scripts tests` | passed; `253 files already formatted` |
| final `uv run --frozen ruff check app scripts tests` | passed; all checks passed |
| `uv run --frozen mypy app scripts/run_phase17b_groq_p17b04_diagnostic.py` | passed; no issues in 130 source files |
| `uv run --frozen pytest -q tests/test_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_groq_benchmark_wrapper.py tests/test_phase17b_groq_governor.py tests/test_groq_evidence_investigator.py tests/test_phase17b_benchmark.py` | passed; `72 passed in 8.40s` |
| `git diff --check` | passed; exit 0 |

This is mocked offline evidence. It does not prove OS behavior after a hard process kill, real
Groq request/response behavior, provider quota accounting, model quality or the historical
request-15 cause. A hard kill intentionally leaves a stale lease and blocks future execution
until operator inspection; the wrapper does not automatically delete it. No diagnostic,
provider, database, worker, corpus, canary or application-tool execution occurred. Phase 17B
remains `PARTIAL`, and the live budget remains `41/150`.

### Full corpus runner preparation — DEC-034/DEC-035

The governed corpus runner now retains DEC-034 sanitized per-turn receipts for every scenario,
including rejection, cancellation, malformed output and governor refusal. Failed or indeterminate
scenarios are recorded and execution continues, preserving all ten denominators. Starts are
counted before transport, paced at least 2.5 seconds apart, and sanitized Groq rate-limit metadata
is retained; 429 is a provider failure with zero retries. An exclusive ignored run lease prevents
concurrent runs. The engine maximum is nine turns per scenario; the diagnostic six-start ceiling
was not the engine limit. The owner-approved full-run ceiling is 90 starts and the live accounting
cap is 250. Offline Ruff, strict mypy and focused Phase 17B tests passed.

The single owner-authorized full corpus run then completed with 16 starts, 15 responses and one
indeterminate provider request; exit status was 1 because thresholds did not pass. Scenarios
p17b-01 and p17b-02 reached terminal responses. p17b-03 failed on turn 3 with HTTP 400 and typed
`provider_rejected`; p17b-04 through p17b-10 were retained as failed cases after governor refusal,
with no silent denominator drops. All ten scenarios are present. The sanitized report and
checkpoint are the new ignored `benchmark-groq-corpus-v2-20261121-owner-final` artifacts. The
budget is now 66/250. This is provider evidence, not a model-quality selection claim; Phase 17B
remains `PARTIAL`.

### Offline correction after governed run review — 22 November 2026

The retained p17b-03 turn-3 receipt contains HTTP 400, typed `provider_rejected`, and the safe
message `Groq evidence investigation failed safely`; raw provider payload, tool declarations,
tool choice and request messages were not retained. The governor previously stopped globally on
every provider error; it now continues after definitive provider outcomes and stops only on
timeout, transient or unknown provider errors. Tool-result messages now retain only standard
role/tool_call_id/content linkage, omitting the deprecated name field. Offline replay tests cover
the retained 400 shape, continuation, timeout stop and request linkage. Ruff, strict mypy, 52
focused tests and diff check passed. No live call was made; Phase 17B remains `PARTIAL` and the
budget remains 66/250.

23 November 2026 offline retry candidate: governor now counts consecutive final transient/timeout
failures and stops after two; definitive failures continue. The governed provider retries only
`tool_use_failed` or transient/timeout once with 2.5-second backoff, and the metered provider
persists attempt number before each transport start. Report scenarios expose first-attempt outcomes
and final outcome separately. Offline Ruff format/lint passed, strict mypy passed (130 source
files), focused pytest passed (55 tests), and git diff --check passed. A mocked retry
after a multi-turn HTTP 400 replayed identical request messages. No corpus was run. One
owner-authorized Groq model-list GET returned HTTP 200 and 11 active model IDs; its response
contains no tool-calling capability field, so no alternative is verified for tool use.

22 November 2026 retention correction: HTTP 400 provider error code/type/message, failed_generation,
and x-request-id now flow through bounded sanitized receipts. Requests retain a tool declaration
SHA-256 and structural message metadata. Removing the tool-message `name` remains an unproven
hypothesis: the earlier p17b-03 turn-2 request already contained a tool result and succeeded.
Offline Ruff format/lint, strict mypy (130 files), focused pytest (53 passed), and git diff --check
passed. The following single corpus run is separately owner authorized; budget before it is 66/250.

The single authorized run wrote new ignored `benchmark-groq-corpus-v2-20261122-owner-retention`
report/checkpoint artifacts and exited 1 after 30 starts, 26 responses, four provider failures,
zero retries. HTTP 400 `tool_use_failed` occurred in p17b-02, p17b-04 and p17b-07; p17b-08
had a transient provider failure, after which the governor refused p17b-09 and p17b-10.
The three 400s continued to later scenarios. All ten cases remain denominated. Provider messages
identify malformed generated tool arguments in two cases and an undeclared `json` tool in one.
Metrics: truth 0.2, required tools 0.3, citations 0.4, abstention 0.0, provider failures 0.6,
malformed outputs 0.0. Budget now 96/250. No rerun authorized; Phase 17B remains `PARTIAL`.

23 November 2026 prompt and receipt correction: Groq-only versioned general instructions now
require one declared function, valid JSON, abstention on unresolved evidence and verified webhook
evidence for disputed authorization. The corpus and thresholds are unchanged. The report retains
the prompt version/hash. Receipt redaction now matches header assignments rather than the bare
word `authorization`; model-facing text and scoring do not use this scrubber. The local governor
still uses a 6,000-token estimated rolling-minute ceiling with a 25% estimate margin; its roughly
60-second pacing is conservative local policy, not proven Groq header enforcement. Offline Ruff
format/lint, strict mypy (130 files), focused pytest (78 passed), and git diff --check passed.

The one authorized versioned-prompt corpus run exited 1 and wrote new ignored
`benchmark-groq-corpus-v2-20261123-prompt-v3` report/checkpoint artifacts. It recorded 37
transport starts, 30 responses, seven failed starts and five retries; budget is 133/250.
All ten scenarios remain in the denominator. p17b-02 and p17b-07 ended on HTTP 400
`tool_use_failed`; first-attempt 400s in p17b-03 and p17b-04 recovered on retry. p17b-09
received one tool response before the local governor's estimated day token ceiling refused the
next turn; p17b-10 was refused before transport. Thus this is not a complete ten-scenario
provider evaluation despite a ten-row report. Metrics: truth 0.3, required tools 0.5,
citations 0.6, abstention 0.0, provider failures 0.4, malformed outputs 0.0. Prompt version
`groq-evaluation-v3-post-corpus-tuning`, SHA-256
`687bbc1f3661030b9adcb43a9c270d3a21633c0c2474d8e86be152c815b3bb75`.
No rerun is authorized; Phase 17B remains `PARTIAL`.

## 23 November 2026 — Mistral second-provider bounded smoke candidate

Owner approved Mistral as a candidate, preserving Groq evidence and disabling Gemini. Preflight:
branch `phase17b/investigator-closure`, HEAD `218b70da3c6c4716bcb4c5d93d675316a6d0d257`,
required Dhanush Git identity, dirty worktree inventoried and preserved, `.env` ignored, Mistral
key present without exposure. A small subclass of the existing strict Groq chat parser changes
only model allowlist, base URL, Mistral tool-result `name` linkage and allowlisted quota metadata;
the common parser is used because it already rejects untrusted calls and never executes tools.
The three-slot smoke runner has one-second minimum spacing, 250,000 TPM configuration, 60-second
timeout, no retry/failover, new ignored output and no application tool executor.

Offline commands from `apps/api`: `uv run --frozen ruff format` on four candidate files passed
(`4 files left unchanged` on final run); `uv run --frozen ruff check app scripts tests` passed;
`uv run --frozen mypy app scripts/run_phase17b_mistral_smoke.py` passed (`131 source files`);
focused `uv run --frozen pytest -q` on Mistral and five existing Phase 17B test files passed
(`86 passed in 10.13s`); `git diff --check` passed. The one owner-authorized model-list request
returned HTTP 200 in 656 ms; no sanitized rate-limit header was present. The candidate
`mistral-large-2512` did not appear in the chat/function-calling-capable model set, so the runner
stopped after request 1. The two authorized chat request slots were not used. Ignored artifact:
`.runtime/phase17b/mistral-smoke-20261123-owner.json`. No corpus, provider tool execution,
PostgreSQL, worker, Groq, Gemini or Razorpay call occurred in this work order. Phase 17B remains
`PARTIAL`; historical Groq budget 133/250 is unchanged.

## 23 November 2026 — Mistral medium remaining smoke slots

The owner approved `mistral-medium-latest` based on the previously saved authenticated model-list
receipt; no model-list request was repeated. The smoke code now records only a closed target
availability status for new model lists and tests all three states. It configures 20,000 TPM,
one request per second, 60-second timeout, one attempt per slot and zero failover. The old
Mistral and Groq modified/untracked paths were preserved. The first offline invocation from the
repository root failed because it did not select the API uv project; no provider request was made.
The corrected invocation from `apps/api` passed Ruff format/check and lint, strict mypy for 131
files, focused pytest `90 passed in 11.38s`, and `git diff --check`.

The first authorized plain POST returned HTTP 429 in 594 ms with no returned model, usage or
allowlisted rate-limit values. It was stored only in new ignored
`.runtime/phase17b/mistral-medium-smoke-continuation-20261123-owner.json`. The smoke stopped.
A guarded forced-only mode was added and validated offline: Ruff, strict mypy and
`91 passed in 11.64s`, diff check passed. It read the prior sanitized model-list and plain-call
receipts and sent one forced-tool POST only, with no model-list or plain repeat. That request
returned HTTP 429 in 453 ms, again without returned model, usage, allowlisted rate-limit values
or tool call. Its new ignored artifact is
`.runtime/phase17b/mistral-medium-forced-only-20261123-owner.json`. Exactly two additional Mistral
requests were made; both failed and consumed their slots. No application tool, corpus, canary,
diagnostic scenario, Groq, Gemini, Razorpay, PostgreSQL or worker execution occurred. Phase 17B
remains `PARTIAL`; historical Groq live budget 133/250 is unchanged.

## 24 November 2026 — Gemini 3.8 Flash isolated smoke

Owner authorization was limited to an isolated `gemini-3.8-flash` smoke with a new Google AI
Studio project/key and at most three requests. Preflight recorded branch
`phase17b/investigator-closure`, HEAD `218b70da3c6c4716bcb4c5d93d675316a6d0d257`, required Git
identity `Dhanush R S <dhanushrs981@gmail.com>`, zero staged paths, 11 modified paths and five
untracked paths before this work order. All were preserved. `apps/api/.env` was confirmed ignored;
`RECLAIMRAIL_GEMINI_38_API_KEY` was present and non-empty without printing, hashing, logging or
serializing its value. The historical Gemini key was not read or used.

Official Google documentation and the installed Google Gen AI SDK 2.34.0 established the current
contract: `gemini-3.8-flash` supports Interactions function declarations; client-side functions
must be executed and returned explicitly for a continuation; SDK decoding continuation defaults
on and must be disabled to enforce one transport attempt; forced selection uses
`generation_config.tool_choice.allowed_tools`; and response format was not combined with function
calling. The new evaluation-only path declares the 11 authoritative read-only tools, disables
continuation, configures SDK attempts to one, never sends a function result and has no application
tool executor.

Offline commands from `apps/api` used a task-local temporary uv cache:

| Command | Result |
| --- | --- |
| `uv run --frozen ruff format --check app scripts tests` | passed; `259 files already formatted` |
| `uv run --frozen ruff check app scripts tests` | passed; `All checks passed!` |
| `uv run --frozen mypy app scripts/run_phase17b_gemini38_smoke.py` | passed; no issues in 132 source files |
| `uv run --frozen pytest -q tests/test_phase17b_gemini38_smoke.py tests/test_gemini_evidence_investigator.py tests/test_phase17b_preflight.py tests/test_phase17b_benchmark.py tests/test_groq_evidence_investigator.py tests/test_phase17b_groq_benchmark_wrapper.py tests/test_phase17b_groq_governor.py tests/test_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_mistral_candidate.py` | passed; `170 passed in 12.35s` |
| `git diff --check` | passed; exit 0 |

The authorized live command was
`uv run --frozen python scripts/run_phase17b_gemini38_smoke.py ../../.runtime/phase17b`.
Request 1 was authenticated model metadata: HTTP 200, 593 ms, requested and returned model
`gemini-3.8-flash`, with no quota metadata. Request 2 was the plain Interactions prompt: one
attempt timed out at exactly 60,000 ms; no HTTP status, returned model, text, input/output/thinking
tokens or quota metadata was available, so exact `OK` was not observed. The runner stopped and did
not start request 3. The unused forced-function slot produced no function name or arguments.

New ignored sanitized artifacts:

- `.runtime/phase17b/gemini38-smoke-20261124T052546Z-1-model_metadata.json`;
- `.runtime/phase17b/gemini38-smoke-20261124T052546Z-2-plain.json`.

No key/header, prompt, objective, observation, raw response, arbitrary provider message, opaque
ID, function result or private evidence was retained. No corpus, canary, diagnostic scenario,
Razorpay, Groq, Mistral, PostgreSQL, worker, evidence-service or application-tool execution
occurred. No frontend evidence was applicable to this evaluation-only smoke. Gemini 3.8 Flash is
available to the isolated project but plain inference and function calling are not technically
verified; it is not ready for a separately authorized evaluation plan. Phase 17B remains
`PARTIAL`; Gemini is not selected; Groq remains unselected and its historical budget/evidence
remains unchanged at `133/250`. No stage, commit, push, deploy or branch switch occurred.

## 24 November 2026 — Gemini 4 Hydrogen bounded smoke

The owner authorized `gemini-4-hydrogen` as the next bounded Phase 17B candidate while explicitly
prohibiting another model-list call and every corpus/canary/diagnostic request. Branch remained
`phase17b/investigator-closure` at `218b70da3c6c4716bcb4c5d93d675316a6d0d257`; Git identity
remained `Dhanush R S <dhanushrs981@gmail.com>` and zero paths were staged. The ignored
`RECLAIMRAIL_GEMINI_38_API_KEY` was used without exposing its value. All existing Groq, Mistral,
Gemini and documentation paths were preserved.

Official Google documentation currently lists the direct Interactions model code as
`gemini-4-hydrogen`, supports thinking levels `low`, `medium`, `high` and `xhigh`, identifies
`low` as the fewest-token/lowest-latency level, and states that `max_output_tokens` includes
thinking tokens. The isolated smoke path was generalized around an explicit allowlist containing
only the preserved `gemini-3.8-flash` path and Hydrogen. Hydrogen skips model metadata, uses low
thinking, 256 maximum output tokens, a 120-second timeout, one attempt, zero retry/failover,
disabled SDK continuation and no automatic/application function executor. Future model-list
sanitation now reads `supported_actions`; no live model-list request was repeated.

Offline commands from `apps/api` used the task-local temporary uv cache:

| Command | Result |
| --- | --- |
| `uv run --frozen ruff format --check app scripts tests` | passed; `259 files already formatted` |
| `uv run --frozen ruff check app scripts tests` | passed; `All checks passed!` |
| `uv run --frozen mypy app scripts/run_phase17b_gemini38_smoke.py` | passed; no issues in 132 source files |
| `uv run --frozen pytest -q tests/test_phase17b_gemini38_smoke.py tests/test_gemini_evidence_investigator.py tests/test_phase17b_preflight.py tests/test_phase17b_benchmark.py tests/test_groq_evidence_investigator.py tests/test_phase17b_groq_benchmark_wrapper.py tests/test_phase17b_groq_governor.py tests/test_phase17b_groq_p17b04_diagnostic.py tests/test_phase17b_mistral_candidate.py` | passed; final rerun `175 passed in 12.43s` |
| `git diff --check` | passed; exit 0 |

The authorized live command was
`uv run --frozen python scripts/run_phase17b_gemini38_smoke.py ../../.runtime/phase17b --model gemini-4-hydrogen`.
Exactly one request started: the plain Interactions request returned HTTP 503 after 31,891 ms,
classified `provider_unavailable`, with typed safe metadata `retry_after_seconds=30`. It returned
no text, returned model ID, token usage or function call, so exact `OK` was not observed. This
failure consumed slot 1 and the runner did not start the forced-function slot.

The one new ignored receipt is
`.runtime/phase17b/gemini4-hydrogen-smoke-20261124T054256Z-1-plain.json`. It contains no prompt,
raw response, arbitrary provider message, header, credential, project/request/interaction ID or
opaque call ID. No function was executed. No corpus, canary, diagnostic scenario, Groq, Mistral,
Razorpay, PostgreSQL, worker, evidence-service or application-tool execution occurred. No
frontend evidence was applicable to this isolated evaluation smoke. Hydrogen generation access
and function calling remain unconfirmed; it is not ready for a separately reviewed evaluation
plan. Phase 17B remains `PARTIAL`; no model was selected and historical Groq evidence/budget
remains unchanged at `133/250`. No stage, commit, push, deploy or branch switch occurred.

## 24 November 2026 — Gemini controlled-canary validation diagnostic

Owner authorized at most six Gemini starts. A bounded enum now covers every response-parser
rejection branch without retaining raw arguments or IDs. The same prompt, declarations, linkage
and frozen observations were preserved; each model was capped at three starts.

Offline: Ruff format/check and lint passed; strict mypy passed for 134 source files; the focused
suite passed `196 passed in 12.34s`; `git diff --check` passed. The one `gemini-3.5-flash` run
made one request and received HTTP 503 after 32,078 ms. The one `gemini-4-hydrogen` run made one
request and received HTTP 503 after 31,969 ms. Both retained retry-after 30 seconds,
`validation_failure_reason=null`, `citations_valid=false`, `truth_compatible=false`,
`failed_safe=true`, and final status `provider_transient_provider`. Exactly two starts were used,
with zero responses, retries, failover or application-tool execution. No other provider, corpus,
database, worker, stage, commit, push or deployment ran.

## 24 November 2026 — offline Gemini retry/fallback and durable report candidate

The read-only Gemini investigator now reads primary and optional fallback model names from
settings/environment. Only HTTP 429/503 is retried, at most twice per model; bounded Retry-After
is preferred, otherwise deterministic 1/2-second backoff is used. After primary exhaustion the
same request uses the fallback. Successful calls log only requested/served model names. The
controlled-canary runner writes and fsyncs the sanitized report before cleanup, and a cleanup
exception no longer replaces the durable result.

Mocked tests cover Retry-After/backoff, retry limits, fallback selection, safe model-only logging,
settings, and report survival across cleanup failure. Targeted validation passed `61 passed`.
The full focused gate passed: Ruff format check `262 files already formatted`, Ruff lint passed,
strict mypy passed for 134 source files, pytest passed `220 passed in 14.05s`, and
`git diff --check` passed. No API request, live canary, stage, commit, push or deployment occurred.

## 25 November 2026 — owner-authorized submission-roadmap amendment

This documentation-only work order inspected `AGENTS.md`, `CURRENT-STATE.md`,
`MASTER-EXECUTION-PLAN.md`, active `ACCEPTANCE-MATRIX.md` rows, `DECISIONS.md`,
the latest `WORK-LOG.md` entries, `UNIFIED-MASTER-ROADMAP.md` and `INVARIANTS.md`.
Pre-edit PowerShell commands included `git status --porcelain=v1 -uall`,
`git branch --show-current`, `git rev-parse HEAD`,
`git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'`,
`git diff --name-only`, `git diff --cached --name-only`,
`git ls-files --others --exclude-standard`, `git log -1 --format=...` and
`Get-Content`/`rg` reads of the authority documents and local sanitized receipt.
Branch was `phase17b/investigator-closure` at
`936b1d6b14e5daa811e260beb85a22ea54996f9f`, tracking
`origin/phase17b/investigator-closure`; the HEAD author and committer were both
`Dhanush R S <dhanushrs981@gmail.com>`. Zero paths were staged. One existing
unstaged spike script and three untracked spike files were preserved exactly.

The latest untracked verification receipt used five starts. Gemini 3.6 Flash
returned HTTP 200 but failed the exact-text check; 3.7 returned 503/504 and 3.8
returned 503/503. The chain was empty and no final ten-scenario corpus report
exists. This is not a Phase 17B quality verdict. No new provider request, corpus,
application code change, payment action or deployment occurred in this work order.

`DEC-041` records the submission-critical provider-backed recovery and safe block,
the five minimum pages, same-cutoff comparison, proposed diagnosis/strategy/
unsent-message contracts and model stop rule. The historical Gate 1A/Gate 2
closures, all existing IDs, current classifications and mandatory P21 receipt
gate remain intact. Six product documents were edited; no `AGENTS.md` change,
stage, commit or push was authorized. The complete six-document `git diff` was
reviewed for unsupported completion claims, contradictory priority/receipt
language, leaked secret shapes and lost requirement IDs. A HEAD-to-worktree ID
set comparison found zero missing IDs in each of the six documents; a scan of
added lines found zero secret-shaped assignments or keys. `git diff --check`
passed with exit 0. No test, lint, build, migration, browser or live-provider
gate ran because this work order changed documentation only; those product
gates remain open where the acceptance matrix says so.

## 25 November 2026 — four-gap roadmap correction, before commit

Owner authorized documentation-only corrections to DEMO-09–11 and the current
next-work instruction. Pre-edit `git status --porcelain=v1 -uall`, branch, HEAD
and staged-name checks found the same `phase17b/investigator-closure` HEAD
`936b1d6b14e5daa811e260beb85a22ea54996f9f`, six modified product docs,
one pre-existing modified spike script, three pre-existing untracked spike
files and zero staged paths. All application/spike work was preserved.

`DEC-042` sets explicit P1 acceptance for verified-field cause diagnosis,
two-cause feasible-intent differentiation and optional deterministic unsent
message validation. `MASTER-EXECUTION-PLAN.md` §23 now labels the Gate 2
instruction historical and names DEC-032 bounded Phase 18 work as current,
without closing the Phase 17B blocker. No runtime, model, Razorpay, browser,
test, lint, build, migration, stage, commit or push action was part of this
documentation correction. The final six-document diff and `git diff --check`
were reviewed after these edits: `git diff --check` passed with exit 0;
HEAD-to-worktree comparison found zero lost requirement/decision IDs, the
roadmap still lists all 50 F-IDs, and the added documentation had zero
secret-shaped matches. Zero paths were staged.
