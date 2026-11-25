# ReclaimRail Master Execution Plan

> **Audit reset — 31 October 2026:** The status ledger and execution order in the
> audit-reset section below supersede older completion language in this file. Historical
> specifications remain requirements unless explicitly replaced in `DECISIONS.md`.

> **Authority:** This is the implementation source of truth for ReclaimRail
> Phases 14–23. It converts the product roadmap into requirements that can be
> implemented, tested and audited. A phase is not complete because code exists;
> every mandatory requirement must have runtime evidence and verification evidence.

- **Plan version:** 2.5-submission-priority-amendment
- **Locked on:** 31 October 2026
- **Evidence refreshed:** 18 November 2026 from Gate 1A closure and final Gate 2 Windows/PostgreSQL validation
- **Unified roadmap status:** owner-approved and locked on 18 November 2026
- **Product:** Evidence-grounded, policy-bounded payment recovery control plane
- **Current merged baseline:** `1912645` (Phase 17 core runtime merged through PR #19)
- **Authoritative continuation:** `gate2/dependency-access-control` at `652e440495ff0d3a9b8c07baa65a24ae2ed2f023`
- **Current phase:** Gate 2 is `VERIFIED` and `CLOSED`; Phase 17B is `PARTIAL` after owner-authorized diagnostics and an incomplete final model verification. `DEC-032` permits deterministic Phase 18 work; Phase 19 remains unauthorized.
- **Verified committed foundation:** Phases 1–5, 14–16 at repository level
- **Partial historical product phases:** 6–13 and 17A
- **Broken closure gate:** Phase 17B live investigator
- **Not implemented against this plan:** Phases 18–23

## 0. Audit-reset execution order

`UNIFIED-MASTER-ROADMAP.md` consolidates product scope, submission priority and the F-01 to
F-50 catalogue. It does not replace this gate sequence or the historical P14–P23 work
orders. Its M0–M8 milestones are crosswalk views only. If the documents conflict, this
execution plan, `CURRENT-STATE.md`, `DECISIONS.md` and `ACCEPTANCE-MATRIX.md` control until
the owner approves a documented replacement.

No implementation phase begins until the owner approves this audit. Each phase below is
independent and ends with a review decision. Do not combine phases to save time.

### Gate 0 — Preserve and normalize the baseline

**Objective:** preserve every staged, unstaged and untracked Phase 17B change, review the
sanitized-out `.env.example` diff, and create a clean reviewable branch without changing
runtime behavior.

Acceptance:

- all 26 changed paths are inventoried;
- staged and unstaged versions are preserved before normalization;
- no secret enters Git;
- no user work is discarded;
- owner identity is verified for author and committer;
- the resulting branch has an explainable diff against `1912645`;
- documentation-only changes and runtime changes are separable; and
- full limitations are recorded in `WORK-LOG.md`.

**Result:** completed by local documentation-only commit
`8dc1655cfae5ac3507e82d766e81b463cdf617dd`. Six approved documentation paths changed,
zero application paths changed, required author/committer identity was preserved, the
worktree was clean and no push occurred.

### Gate 1 — Reproduce the committed/runtime baseline

**Objective:** establish a current Windows/Docker evidence baseline before feature work.

Acceptance:

- clean PostgreSQL and Redis start from the tracked PowerShell controller;
- Alembic upgrades from base to the single head and `alembic check` passes;
- backend suite has zero failures and every skip is explained;
- frontend lint and production build pass;
- one signed Test Mode webhook is stored and projected without duplication;
- the frontend reads the same persisted case; and
- no live Gemini corpus is run.

**Result:** `BROKEN`. Infrastructure, migrations, backend quality, frontend compilation,
controller startup, signed intake, duplicate handling and payment projection passed. The
tested payload was locally signed controlled synthetic evidence, not provider-emitted Test
Mode evidence. The Payment Lab recovery worker then produced 453 consecutive unavailable
provider-read batches, timestamp-unique equivalent evidence and repeated truth versions.
The deterministic truth gate moved the payment to `manual_investigation_required`, case
creation correctly returned `recovery_not_eligible`, and same-case frontend proof could
not be completed. No application code was changed and no live Gemini corpus ran.

### Gate 1A — P0 bounded reconciliation remediation

**Objective:** close `G1-P0-001` without weakening deterministic truth or hiding provider
ambiguity. This gate must close before Gate 2 or any feature phase.

Acceptance:

- unavailable/manual-investigation candidates obey a persisted cooldown and bounded
  exponential backoff rather than being selected on every poll;
- equivalent provider-unavailable evidence is idempotent within the retry window and does
  not create a new truth snapshot without new information;
- retry/circuit state survives worker batches and restart, has an explicit maximum budget,
  and is visible in health/operations evidence;
- controlled synthetic identifiers cannot reach a live Razorpay adapter;
- provider unavailability still fails safely to manual investigation and never authorizes
  recovery;
- fresh matching provider evidence can supersede expired unavailable evidence and restore
  the correct deterministic truth;
- focused tests cover repeated polling, two concurrent workers, restart, provider recovery,
  stale evidence and evidence uniqueness;
- no live Gemini request is made;
- one bounded Razorpay Test Mode verification is attempted only after deterministic tests
  pass and the owner approves that provider-read evidence;
- complete Gate 1 is rerun on a fresh isolated database; and
- the same persisted eligible case is rendered and understandable in the frontend.

**Historical authorization condition — satisfied 17 November 2026:** no Gate 1A
application change was authorized until the owner approved its implementation scope and
planned changed files.

**Current result:** `VERIFIED`. The owner authorized Gate 1A and its local closure commit
passes migration, static quality, focused and complete
backend tests, frontend lint/build, controlled restart, complete-controller and inspected
responsive frontend gates. Requirements G1A-01 through G1A-08 are `VERIFIED`.

The controlled runtime used a fresh database, isolated Redis logical DB 15, the API, web
and target recovery worker. It proved zero calls inside cooldown/open circuit, stable
evidence/truth counts, durable state across restart, synthetic blocking, safe manual
investigation, provider-stub recovery and frontend worker metrics. A separate fresh full
controller run started all 11 processes with API ready and 8/8 workers healthy. Final
screenshots were manually inspected at 1024/1440/1920 plus the populated case. Final
evidence archive SHA-256:
`4af876f59b72da82aa330a0848ac9d29ab8c5175b9325802ca6d09ea92987f71`.

Provider-emitted Razorpay Test Mode proof was not authorized and is explicitly retained as
a later provider-backed journey requirement; controlled evidence is not relabelled as live.
The exact staged paths, diff checks and required identity were verified before the local
23-path closure commit. No push was authorized or performed. Gate 2 is now the next work
order.

### Gate 2 — Dependency and access-control stabilization

**Objective:** remove current critical/high dependency findings and define the public-demo
access boundary without mixing product features into the upgrade.

Acceptance:

- supported Next.js and transitive packages are locked;
- Python runtime findings are upgraded, removed or explicitly risk-accepted by the owner;
- npm and Python audits have no unaccepted critical/high findings;
- all existing tests, migrations and builds pass;
- server-side secrets remain server-only;
- the owner decides which read APIs require protection for the chosen deployment mode;
- browser evidence proves protected and denied paths; and
- no recovery semantics change silently.

Final technical result, 18 November 2026: `VERIFIED`. The controlled-reviewer boundary,
server-only mutation tokens and browser session flow passed denial/authenticated/logout
HTTP checks. The exact candidate passed the three PostgreSQL integration tests, complete
backend suite (`721 passed, 1 skipped`), base-to-head migration, backend static quality,
frontend lint/build, fresh 11-process controller startup and 8/8 worker health. Runtime and
complete Python audits plus the npm production audit contain zero known vulnerabilities.

The complete npm audit retains one unpatched lint/build-only `picomatch` advisory represented
as 14 transitive high findings. Under `DEC-029`, the owner accepts that bounded dev-only
risk until an upstream compatible fix exists; the acceptance expires before hosted/public
deployment or Phase 21 closure and does not permit `npm audit fix --force`. Runtime logs
contained zero Razorpay/Gemini network findings, and no provider/model call was authorized.
Final evidence SHA-256:
`fea6daa02efa9cb202a5906b9f463e002caab4d1353b26d698a100b0462227e7`.

Gate 2 is `VERIFIED` and `CLOSED` by commit
`652e440495ff0d3a9b8c07baa65a24ae2ed2f023`. Author and committer are
`Dhanush R S <dhanushrs981@gmail.com>`; exactly 46 paths were committed; the worktree was
clean; the branch was pushed successfully; local and remote hashes matched; and upstream
tracking was configured. No force push, pull request, merge or deployment occurred.
Phase 17B remains unauthorized pending a separate owner decision.

### Gate 3 — Phase 17B live investigator closure

**Objective:** close the existing investigator honestly, using one controlled benchmark
after deterministic diagnostics.

Acceptance:

- supported model routes contain no deprecated duplicate masquerading as failover;
- a cheap access/quota/schema preflight passes before the corpus;
- the frozen corpus and thresholds are hashed and unchanged;
- one approved live run records complete sanitized evidence;
- truth compatibility and required-tool selection are each at least 80%;
- citation validity is 100%;
- abstention accuracy is at least 80%;
- provider-failure and malformed-output rates are 0% for model selection;
- no AI action can mutate truth, approval or Razorpay;
- incomplete/fallback/abstained states are visible in the frontend; and
- PostgreSQL, backend, frontend and security gates pass on the committed phase branch.

If provider quota prevents a complete run, record the phase as `PARTIAL` with an explicit
external blocker; do not weaken thresholds or repeat the corpus until the external condition
and budget are reviewed.

**25 November stop rule:** after one bounded, complete model evaluation, publish the
pass/failure decision against these unchanged thresholds and stop model search and
prompt tuning. A verification with no eligible model and no corpus is incomplete,
not a quality verdict; any further live attempt needs a separate owner decision.

### Gate 4 — Phase 18: evidence validation and action ranking

Implement the existing P18 specification in this document. In addition to its detailed
requirements, completion requires frontend proof of supported and rejected claims,
case-owned citations, feasible alternatives, ranking inputs and the final coordinate-free
intent. Semantic validation cannot be represented by the Phase 17 citation-presence check.

### Gate 5 — Phase 19: policy and state-bound approval

Implement the existing P19 specification. Older approval code is reusable only after it
proves binding to case version, truth version, evidence digest, exact action, backend-resolved
amount, approver and expiry. New evidence must atomically invalidate stale authorization.

### Gate 6 — Phase 20: durable provider execution

Implement the existing P20 specification. Older executor code is reusable only after it
passes durable-intent-before-mutation, deterministic idempotency, concurrency, ambiguity,
reconciliation-before-retry and restart/recovery gates. Every attempt must be visible.

### Gate 7 — Phase 21: security, resilience and receipts

Implement the existing P21 specification plus the approved deployment/access decision.
Completion includes dependency security, ownership/tenant enforcement, rate/abuse controls,
redaction, restart drills and a tamper-evident receipt binding truth through outcome.

### Gate 8 — Phase 22: Investigation Room

Implement the existing P22 specification as the single judge-facing evidence workflow. It
must expose objective, deterministic truth, bounded tools, hypotheses, validated claims,
alternatives, policy, approval, execution and outcome without private chain-of-thought.

Completion requires automated browser behavior, keyboard/contrast checks, approved
1024/1440/1920 evidence and truthful empty/error/fallback/abstention states.

### Gate 9 — Phase 23: measured evaluation and submission

Implement the existing P23 specification and Razorpay Track 3 bar.

Acceptance additionally requires:

- a reproducible cohort with a meaningful baseline/control rather than a zero placeholder;
- denominators, exception list, pending outcomes and confidence/uncertainty;
- separate synthetic, replay and Razorpay Test Mode results;
- no production-revenue language for Test Mode money;
- clean-clone Windows setup proof;
- a five-minute unlisted/public demo video;
- README links, architecture, limitations and failure-recovery story;
- a final evidence bundle containing commands, reports and frontend proof; and
- owner review before any application is submitted.

### 25 November submission sequence within the existing gates

`DEC-041` prioritizes one provider-backed recovery and one safely blocked case; it
does not authorize Phase 19–23 implementation or waive any mandatory exit gate.
Gate 3/Phase 17B stays `PARTIAL`; `DEC-032` allows the first implementation work
order to be **Phase 18 deterministic claim validation**, especially P18-01–09 and
F-14/F-18, after this documentation diff is reviewed. Preserve the existing
contract → persistence → domain → adapters → workers/API → negative/race tests →
frontend evidence → docs implementation order. Phase 19 then binds approval;
Phase 20 proves durable intent, link lifecycle and reconciliation; Phase 21 closes
security and the mandatory receipt; Phase 22 exposes the complete investigation;
Phase 23 validates the two live demonstrations and comparison. Each phase still
ends at its own owner review.

The first provider-backed demonstration must retain a single chain of backend IDs:
genuine Test Mode payment/order → verified failed evidence → truth version → case →
bounded read-only investigation → validated claims and feasible intent → policy
verdict and state-bound approval if required → committed provider intent → backend-
supplied official Payment Link → provider-confirmed paid link/payment → exactly one
attributed Test Mode ledger outcome. A created link remains pending, not recovered.
The blocked demonstration must persist a denial or abstention reason and prove zero
provider mutation. Test Mode capability, actual failure category and notification
support are `NEEDS INSPECTION` until provider/account evidence is recorded.

| Step | Required frontend proof from persisted backend evidence |
| --- | --- |
| Failure, truth, case | Command Center risk and Recovery Cases row/detail show Test Mode provenance, source ID, failed/unknown distinction, truth version, eligibility and case ID. |
| Investigation, claims | Investigation Room shows tool/claim citations, same-case cutoff and semantic validation results, rejected facts, abstention/fallback and selected feasible alternative. |
| Policy, review | Investigation Room and Human Reviews show rule codes, hard stops, grant binding, expiry and stale invalidation; blocked case has no actionable link. |
| Intent, link, payment | Investigation Room shows intent/attempt/idempotency and reconciliation state; only the backend supplies the official link; pending action/payment remain distinct. |
| Outcome | Outcome Ledger and Command Center show provider confirmation, case/link/payment attribution, one Test Mode recovered amount and reload-safe history. |

Cause-specific diagnosis, strategy selection and a prepared **unsent** customer
message are proposed improvements with acceptance in DEMO-09–11. DEMO-09 requires
verified same-case provider fields at the evidence cutoff; unknown or ambiguous
fields cannot support a specific cause. DEMO-10 requires two distinct verified
causes to produce different feasible intents when policy allows, while an
unsupported cause cannot change the action. DEMO-11 is optional P1: deterministic
fact/language/length/credential/consent/provenance checks precede backend link
insertion; show `PREPARED_NOT_SENT` until delivery is verified. None of these
improvements gives AI financial authority or makes message preview a core-recovery
dependency. A small rule-
only versus AI-assisted paired comparison uses the same frozen evidence cutoff;
naive unsafe strategy runs only in isolated simulation. Keep the four-arm Phase 23
requirement and P21-07/08 receipt/verifier as release gates. Deferring the core
receipt would leave Phase 21 and release `PARTIAL` pending separate owner approval.

## 1. Why this document exists

This document prevents four recurring failures:

1. forgetting requirements agreed earlier;
2. implementing only the visible UI while backend proof is missing;
3. calling scaffolding or unit tests a completed production path; and
4. adding attractive features that weaken the payment-safety thesis.

Every implementation session must begin by reading:

1. `docs/INVARIANTS.md`;
2. this document;
3. the current phase section in this document;
4. the current phase-specific document; and
5. the latest merged build log and open pull-request diff.

If chat instructions conflict with a safety invariant, the invariant wins. If a
new product decision changes this plan, update this file in the same pull request
as the implementation. Never silently omit or redefine an agreed requirement.

## 2. Product thesis and proof standard

ReclaimRail does not treat an AI response, browser callback, network error or
message-provider acceptance as financial truth. It:

1. establishes versioned payment truth from stored evidence;
2. lets an AI investigator gather bounded, read-only evidence and abstain;
3. validates every AI claim against cited evidence;
4. ranks safe recovery alternatives;
5. lets deterministic policy and version-bound approval authorize an action;
6. records durable intent before any provider mutation;
7. reconciles ambiguous outcomes before retrying; and
8. produces an auditable, tamper-evident decision and outcome receipt.

The product must prove three different outcomes separately:

| Outcome | Meaning | Required proof |
| --- | --- | --- |
| Action success | ReclaimRail executed an allowed action | durable attempt and provider acknowledgement |
| Payment success | Razorpay confirms a payment state | provider API or verified signed webhook evidence |
| Attributed recovery | The action caused a verified recovery payment | verified payment plus action/case attribution |

Test Mode, replay and synthetic results must always remain visibly distinct.

## 3. Authority boundaries

### 3.1 Components allowed to decide

| Concern | Authority |
| --- | --- |
| Payment chronology and truth | deterministic truth resolver |
| Evidence ownership and freshness | backend validation |
| Hypothesis generation | Gemini investigator |
| Tool selection | Gemini within a read-only allow-list |
| Claim validity | deterministic claim validator |
| Candidate-action feasibility | deterministic capability filter |
| Candidate ranking | bounded economic ranker |
| Permission to act | deterministic policy engine |
| Protected exception | version-bound human approval |
| Amount, customer, provider resource | trusted backend resolution |
| Financial outcome | provider verification and reconciliation |

### 3.2 AI may never

- declare payment truth;
- change payment state directly;
- choose or modify the amount;
- invent customer contact details or provider IDs;
- bypass policy, approval, cooldowns or retry budgets;
- call a provider-changing tool during investigation;
- cite evidence from a different case or from the future;
- convert low confidence into permission;
- report simulated recovery as real revenue; or
- expose private chain-of-thought.

The UI may show structured hypotheses, cited claims, tool calls, alternative
actions and closed reason codes. It must not claim to show hidden model reasoning.

## 4. Non-negotiable system invariants

The detailed contract remains in `docs/INVARIANTS.md`. The delivery-critical
summary is:

1. `UNKNOWN` never means `FAILED`.
2. Only verified, case-owned evidence may establish payment truth.
3. Every truth snapshot is immutable and versioned.
4. New material evidence invalidates stale plans, approvals and executable work.
5. Every AI claim cites stored evidence available at decision time.
6. AI emits only a coordinate-free intent; the backend resolves trusted values.
7. No Razorpay-changing call occurs without committed durable intent.
8. Provider ambiguity becomes `IN_FLIGHT` or reconciliation-required, not blind retry.
9. Every mutation is idempotent and reconciliation precedes retry.
10. Money is integer minor units with an explicit currency.
11. Provider-confirmed outcomes are distinct from application/action success.
12. Recovery notifications require capability, consent and policy permission.
13. Test Mode, replay and synthetic evidence are never combined into production claims.
14. Missing metrics remain unavailable; they never become invented zeroes.
15. All high-impact decisions retain model, prompt, tool, evidence and policy versions.

## 5. Delivery workflow that must be followed

### 5.1 Start-of-phase gate

Before writing phase code:

- [ ] `main` is clean and synchronized with `origin/main`.
- [ ] Previous phase pull request is merged and its final CI is green.
- [ ] Previous phase status and verification evidence are recorded here.
- [ ] A dedicated branch is created from the verified baseline.
- [ ] Mandatory requirement IDs for the phase are copied into the PR description.
- [ ] Existing behavior that must remain compatible is identified.

Branch format: `phase-<number>/<short-scope>`.

### 5.2 Implementation order inside every phase

1. contracts and invalid states;
2. persistence and migration, if required;
3. deterministic domain behavior;
4. services and provider adapters;
5. worker/API wiring;
6. negative, race and failure tests;
7. reviewer-facing proof;
8. documentation and build log;
9. full backend/frontend/repository gate.

### 5.3 Definition of done

A mandatory requirement can be marked complete only when all applicable columns
are filled:

| Requirement | Contract | Runtime path | Persistence | Failure behavior | Automated test | Reviewer proof |
| --- | --- | --- | --- | --- | --- | --- |
| Example | schema/enum | service/worker/API | table/record | fail-closed result | test name | API/UI/receipt |

Not sufficient by itself:

- file creation;
- mocked happy-path test;
- UI text;
- a model returning JSON once;
- a screenshot;
- provider API acceptance without reconciliation;
- a passing focused test while the full suite fails.

### 5.4 Change-control rule

Requirements use stable IDs. They may be:

- **completed** — runtime and proof gates passed;
- **pending** — not implemented;
- **blocked** — external dependency documented with safe fallback;
- **deferred** — explicitly moved without being called complete; or
- **replaced** — superseding requirement and reason recorded.

No requirement may disappear from this file. New work must identify whether it is
mandatory, important or stretch. Stretch work cannot delay the mandatory path.

## 6. Locked end-to-end workflow

```mermaid
flowchart TD
    A["Signed events and provider reads"] --> B["Versioned payment truth"]
    B --> C["Read-only AI investigation"]
    C --> D["Cited claims and candidate intents"]
    D --> E["Economic ranking and policy"]
    E --> F["Version-bound approval"]
    F --> G["Durable provider execution"]
    G --> H["Reconciliation and receipt"]
    H --> I["Outcome ledger and evaluation"]
```

Every arrow must correspond to persisted or reproducible evidence. A frontend
animation may visualize the workflow but may not create a stage or timestamp.

## 7. Phase status ledger

| Phase | Scope | Status | Merge/build evidence |
| --- | --- | --- | --- |
| 14 | Safety invariants and contracts | **Complete** | PR #15 lineage; typed contracts, ADRs and invariant tests |
| 15 | Versioned Payment Truth Resolver | **Complete** | PR #16 plus Phase 16 corrective completion |
| 16 | Reliable events and reconciliation | **Complete at Gate 1A scope** | committed bounded reconciliation, deterministic/full-controller/browser evidence; provider-backed provenance remains a later separate gate |
| 17 | Gemini Evidence Investigator | **Corrective closure** | Core runtime merged in PR #19; live frozen-corpus report pending |
| 18 | Evidence validation and action ranking | Pending | — |
| 19 | Policy and state-bound approval | Pending | — |
| 20 | Durable provider execution | Pending | — |
| 21 | Security, resilience and receipts | Pending | — |
| 22 | Investigation Room | Pending | — |
| 23 | Scenario Lab, evaluation and submission | Pending | — |

## 8. Phase 14 — Safety invariants and contracts

### Objective

Express the authority and safety boundaries as types and negative tests before
changing runtime behavior.

### Mandatory requirements

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| P14-01 | Payment evidence and versioned truth contracts | Complete | `domain/recovery/contracts.py` and tests |
| P14-02 | Cited claim and investigation-hypothesis contracts | Complete | typed validation and negative tests |
| P14-03 | Coordinate-free recovery-intent contract | Complete | trusted coordinates excluded |
| P14-04 | Policy decision and state-bound approval contracts | Complete | invalid approval combinations rejected |
| P14-05 | Durable provider-attempt and receipt contracts | Complete | execution/receipt shapes validated |
| P14-06 | Architectural invariants and ADRs | Complete | `INVARIANTS.md`, ADR-0002 through ADR-0005 |
| P14-07 | Existing runtime behavior remains compatible | Complete | full regression gate |

### Completion proof

Phase 14 is closed. Later phases may extend the contracts but may not weaken their
authority boundaries.

## 9. Phase 15 — Payment Truth Resolver

### Objective

Determine what happened to a payment from immutable evidence before recovery is
allowed. Arrival order alone is never truth.

### Required evidence sources

- Razorpay payment API;
- Razorpay order/payment listing;
- verified signed webhooks;
- merchant/internal `PaymentAttempt` projection;
- Payment Lab provenance;
- previous recovery case/action state;
- reconciliation observations; and
- recovery-link and recovery-payment status.

### Truth states

`PAYMENT_CONFIRMED`, `PAYMENT_FAILED`, `PAYMENT_PENDING`, `OUTCOME_UNKNOWN`,
`SOURCE_CONFLICT`, `LATE_AUTHORIZATION`, `RECOVERY_ALREADY_ACTIVE`,
`RECOVERY_CONFIRMED`, and `MANUAL_INVESTIGATION_REQUIRED`.

### Mandatory requirements

| ID | Requirement | Status | Runtime and proof |
| --- | --- | --- | --- |
| P15-01 | Append-only evidence record with source identity and source record | Complete | evidence model/service/tests |
| P15-02 | Event time, observation time, freshness and reliability | Complete | stored columns and case-detail proof |
| P15-03 | Signature/verification state, normalized fields and SHA-256 | Complete | webhook/provider evidence tests |
| P15-04 | Immutable versioned truth snapshot with evidence digest | Complete | truth model/service/migration |
| P15-05 | Deterministic nine-state resolver | Complete | truth scenario matrix |
| P15-06 | Source conflict and identity-mismatch fail closed | Complete | conflict codes and negative tests |
| P15-07 | Provider unavailability is durable evidence, not failure | Complete | manual-investigation resolution |
| P15-08 | Captured state overrides timeout uncertainty | Complete | provider reconciliation path |
| P15-09 | Late authorization stops recovery | Complete | atomic integration path |
| P15-10 | New material truth invalidates stale work | Complete | case version bump, plan/action/approval invalidation |
| P15-11 | Duplicate evidence does not create duplicate truth | Complete | evidence identity and snapshot suppression |
| P15-12 | Reviewer API/UI exposes truth and cited evidence | Complete | case detail endpoint and frontend build |

### Closed verification

The Phase 15 migration and runtime correction were included in the Phase 16
completion merge. This is intentional corrective completion, not skipped work.

## 10. Phase 16 — Reliable events and reconciliation

### Objective

Ensure duplicate, delayed, missing, reordered or ambiguous delivery cannot corrupt
truth or create duplicate recovery.

### Mandatory requirements

| ID | Requirement | Status | Runtime and proof |
| --- | --- | --- | --- |
| P16-01 | Raw-body HMAC verification and invalid-signature rejection | Complete | webhook route and endpoint tests |
| P16-02 | Canonical idempotency and duplicate detection | Complete | unique identities and projection tests |
| P16-03 | Monotonic out-of-order handling | Complete | ignored regression transition proof |
| P16-04 | Seven-day event-age fail-closed policy | Complete | stale event stored but not projected |
| P16-05 | Unsupported event retained and safely skipped | Complete | processor disposition test |
| P16-06 | Provider error taxonomy | Complete | network/connect/read/429/4xx/5xx/malformed |
| P16-07 | Provider success plus DB failure remains an explicit persistence error | Complete | reconciliation failure path |
| P16-08 | Global stale/conflicting/missing-event reconciliation | Complete | provider polling worker/service tests |
| P16-09 | Retry budget and DLQ | Complete | consumer tests |
| P16-10 | Single-entry controlled replay with operator and reason | Complete | durable replay audit and duplicate rejection |
| P16-11 | Transactional outbox, locks and worker claims | Complete | transaction/claim tests |
| P16-12 | Bounded exponential backoff and jitter | Complete | deterministic bound tests |
| P16-13 | Provider circuit breaker | Complete | opens after three consecutive provider failures |
| P16-14 | Worker supervision/heartbeat | Complete | existing supervised workers and health tests |
| P16-15 | Truth change invalidates in-flight stale recovery work | Complete | integration tests |
| P16-16 | Reviewer sees event provenance and reliability | Complete | API/UI fields, lint and build |
| P16-17 | Provider-read retry state is durable across polls/restart and visible to operators | Complete | committed Gate 1A migration, service/worker tests, controlled restart and Safety Controls metrics pass |

### Closed verification record

- backend: **669 passed, 1 skipped**;
- Ruff format/check: passed;
- strict mypy: passed;
- Alembic upgrade and schema check: passed;
- frontend lint and production build: passed;
- npm audit: zero vulnerabilities;
- merge: `67c950c`;
- owner-only author/committer identity verified.

## 11. Phase 17 — Gemini Evidence Investigator

### Objective

Replace the weak one-shot planner with a bounded investigator that decides what
read-only evidence to inspect, maintains explicit hypotheses, cites observations,
and may abstain. The deterministic answer must not be embedded in its prompt.

### Why this phase matters

The standout proof is not that Gemini can produce a recovery paragraph. It is that
different live evidence causes different tool sequences, hypotheses and abstention,
while truth and financial authority remain outside the model.

### Runtime architecture

```mermaid
flowchart TD
    A["Case objective and truth reference"] --> B["Gemini chooses read-only tool"]
    B --> C["Backend validates case ownership"]
    C --> D["Tool returns stored evidence IDs"]
    D --> E["Hypothesis ledger updates"]
    E --> F{"Enough evidence?"}
    F -->|No, budget remains| B
    F -->|Yes| G["Structured investigation result"]
    F -->|Unsafe or exhausted| H["Abstain or deterministic fallback"]
```

### Read-only tool registry

Each tool must have a strict request/response schema, enforce the current case,
return evidence IDs and provenance, redact secrets, and have a timeout.

| ID | Tool | Purpose | Never returns/does |
| --- | --- | --- | --- |
| T17-01 | `get_truth_snapshot` | current and selected historical truth | never changes truth |
| T17-02 | `get_provider_payment` | server-side provider payment observation | no mutation or browser callback |
| T17-03 | `get_provider_order` | order and associated payment observations | no arbitrary merchant resource |
| T17-04 | `get_verified_webhooks` | signed lifecycle evidence | excludes unverified claims from truth |
| T17-05 | `get_internal_payment` | merchant projection and version | no direct state update |
| T17-06 | `get_recovery_history` | prior plans/actions/approvals/outcomes | no approval or execution |
| T17-07 | `get_payment_link_status` | owned recovery-link state | no link creation |
| T17-08 | `get_route_health` | incident/rail health evidence | labels drills/synthetic data |
| T17-09 | `get_merchant_policy_summary` | safe capability summary | redacts exploitable thresholds where required |
| T17-10 | `get_customer_contact_capabilities` | consented channels/capability only | redacts raw contact data from model |
| T17-11 | `get_similar_outcomes` | aggregate comparable outcomes | no cross-merchant PII or future outcomes |

Provider reads made by tools must enter the evidence ledger before the model may
cite them. A raw external response is not passed directly as trusted truth.

### Persisted investigation entities

The implementation must persist equivalent records (names may change only with a
documented migration decision):

#### Investigation session

- session ID;
- recovery case ID and case version;
- starting truth snapshot/version;
- evidence cutoff timestamp;
- status: `RUNNING`, `COMPLETED`, `ABSTAINED`, `FALLBACK`, `FAILED_SAFE`;
- model provider/name/version;
- prompt-template version;
- tool-registry version;
- token/tool/time budgets;
- start/end timestamps;
- terminal reason and result digest.

#### Investigation step

- sequence number;
- requested tool and validated arguments;
- tool start/end and outcome;
- evidence IDs returned;
- redacted error classification;
- model response digest;
- cumulative budget consumption.

#### Hypothesis record

- stable hypothesis ID and concise claim;
- status: `OPEN`, `SUPPORTED`, `CONTRADICTED`, `UNRESOLVED`, `REJECTED`;
- supporting and contradicting evidence IDs;
- missing evidence/questions;
- next proposed observation;
- first/last step and version.

Do not persist private chain-of-thought. Persist only structured, reviewer-safe
hypotheses, claims, observations, decisions and tool transcript.

### Mandatory requirements

| ID | Requirement | Verification target |
| --- | --- | --- |
| P17-01 | Versioned, allow-listed read-only tool registry | unknown/mutating tools rejected |
| P17-02 | Case ownership and temporal evidence cutoff on every tool | cross-case and future evidence tests |
| P17-03 | Durable investigation session and ordered step transcript | restart/reload preserves exact trace |
| P17-04 | Persisted structured hypothesis ledger | support/contradict/reject scenario tests |
| P17-05 | Bounded loop with tool, token, model-retry and wall-clock budgets | each exhausted budget fails safely |
| P17-06 | Structured model output validated before use | malformed/extra-field/unknown-enum tests |
| P17-07 | Prompt contains objective and available tools, not baseline answer | prompt-contract snapshot test |
| P17-08 | Explicit abstention when evidence is insufficient or conflicting | abstention scenarios |
| P17-09 | Deterministic fallback is labelled and cannot impersonate Gemini | timeout/quota/malformed tests |
| P17-10 | Provider adapter isolates Gemini-specific protocol | fake adapter plus real configured adapter contract |
| P17-11 | Secrets and raw contact details never enter prompt/transcript | redaction tests |
| P17-12 | Tool observations are ledgered before citation | provider-read persistence integration test |
| P17-13 | Concurrent/repeated investigation is idempotent per case version | duplicate worker/race test |
| P17-14 | New case/truth version supersedes stale investigation | version invalidation integration test |
| P17-15 | Case API exposes reviewer-safe investigation trace | endpoint contract test |
| P17-16 | Shadow mode runs investigator without authorizing action | no execution-side-effect test |

### Model selection experiment

Do not switch models based on marketing claims or a student subscription alone.
Run the same frozen scenario corpus through eligible models/adapters and record:

- truth-compatible conclusion rate;
- correct tool selection and tool efficiency;
- valid citation rate;
- unsupported-claim rate;
- abstention precision/recall;
- malformed-output rate;
- p50/p95 latency;
- token usage and cost/quota consumption; and
- fallback frequency.

The default model is chosen only after the benchmark. The project must remain
functional when the selected model is unavailable.

### Required scenarios

1. verified failure with sufficient evidence;
2. timeout but captured, requiring provider observation;
3. missing webhook with order/payment lookup;
4. conflicting sources requiring abstention;
5. provider unavailable requiring manual investigation;
6. active recovery preventing a duplicate proposal;
7. late authorization superseding the investigation;
8. malicious text attempting to invoke a forbidden tool;
9. model timeout/quota/malformed output;
10. repeated worker delivery without duplicate session effects.

### Phase 17 completion gate

- [ ] P17-01 through P17-16 have runtime and test evidence.
- [x] At least three cases produce meaningfully different tool sequences.
- [x] No baseline/deterministic answer is leaked into the model prompt.
- [x] Cross-case, future and unverified evidence cannot be cited.
- [x] Timeout, quota, malformed output and tool failure all fail safely.
- [x] Shadow mode proves the investigator cannot execute recovery.
- [ ] Full backend, migration, frontend and CI gates pass.
- [ ] Phase document and build log contain measured results, not adjectives.

### Explicitly not in Phase 17

Action ranking, final policy authorization, provider mutation and the major UI
redesign belong to later phases. Phase 17 may expose a minimal trace for proof but
must not pull Phase 22 forward.

## 12. Phase 18 — Evidence validation, confidence and action ranking

### Objective

Turn the investigation into validated claims and ranked coordinate-free recovery
intents without giving the model execution authority.

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P18-01 | Deterministic claim validator | every claim cites same-case evidence |
| P18-02 | Temporal-leakage firewall | evidence observed after decision cutoff is rejected |
| P18-03 | Claim-to-evidence semantic checks | claimed fact/value must match normalized evidence |
| P18-04 | Freshness and truth compatibility | stale/contradictory claims fail closed |
| P18-05 | Multi-dimensional confidence | truth certainty, completeness, freshness, decision margin and agreement remain separate |
| P18-06 | Honest calibration state | insufficient labels display `NOT_CALIBRATED` |
| P18-07 | Coordinate-free intent | model cannot set amount/contact/provider resource |
| P18-08 | Backend trusted-coordinate resolution | values derive from case, merchant and provider records |
| P18-09 | Feasible candidate generator | only supported, policy-evaluable actions enter ranking |
| P18-10 | Economic action ranker | expected recovery minus cost/harm/duplicate risk |
| P18-11 | Counterfactual alternatives | store why the winner outranked or excluded alternatives |
| P18-12 | Ranking provenance | feature/model/formula version and inputs are reproducible |

### Allowed intent types

`WAIT_FOR_AUTH`, `RETRY_LATER`, `CREATE_PAYMENT_LINK`, `CHANGE_METHOD`,
`ESCALATE`, and `DO_NOT_RECOVER`.

### Economic ranking

For every feasible action, record a decomposed score rather than only a final number:

$$
ENR = P(recovery \mid case, action) \times amount
- action\ cost - customer\ harm - duplicate\ risk
$$

If recovery probability is uncalibrated, rank with an explicitly versioned
heuristic/interval and label it; do not invent a percentage.

### Completion gate

- unsupported or future-cited claims are rejected;
- trusted coordinates never come from Gemini;
- every candidate has feasibility and exclusion reasons;
- the selected action has reproducible score components;
- unsafe uncertainty leads to abstain/escalate, not forced ranking; and
- identical frozen inputs reproduce the same deterministic validation result.

## 13. Phase 19 — Deterministic policy and state-bound approval

### Objective

Authorize only an exact backend-resolved action against the latest truth and case
version. Human approval may satisfy an approval requirement but never override a
hard denial.

### Mandatory policy inputs

- current truth and truth version;
- case version and evidence digest;
- duplicate-payment risk and active recovery;
- maximum attempts, cooldown and quiet hours;
- amount/currency and merchant limits;
- route incident and provider capability;
- customer contact consent/capability;
- required evidence and freshness;
- action capability and stop conditions; and
- approval requirement and expiry.

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P19-01 | Closed policy decision codes | no free-text-only authorization |
| P19-02 | Explainable per-rule results | actual value, expected bound and evidence reference |
| P19-03 | State-bound approval grant | binds case/truth/action/amount/evidence digest |
| P19-04 | Approval expiry and approver identity | immutable audit fields |
| P19-05 | New evidence invalidation | version change expires approval before execution |
| P19-06 | Revalidation at decision time | reviewer cannot approve already-stale work |
| P19-07 | Revalidation immediately before execution | race-window protection |
| P19-08 | Hard denials are non-overridable | approval cannot bypass captured/unknown/active/forbidden state |
| P19-09 | Dual-control option for high-risk configured actions | distinct approvers when policy requires it |
| P19-10 | Global and merchant recovery kill switches | safe stop independent of model availability |

### Closed decision examples

`ALLOW`, `REQUIRE_APPROVAL`, `DENY_PAYMENT_ALREADY_CAPTURED`,
`DENY_TRUTH_UNCERTAIN`, `DENY_RECOVERY_ACTIVE`, `DENY_MAX_ATTEMPTS`,
`DENY_STALE_EVIDENCE`, `DENY_ROUTE_INCIDENT`,
`DENY_CONTACT_NOT_PERMITTED`, and `DENY_KILL_SWITCH_ACTIVE`.

### Completion gate

Normal allow, protected approval, rejection, expiry, new-evidence invalidation,
concurrent decision, hard denial and kill-switch scenarios must pass end to end.

## 14. Phase 20 — Durable and idempotent provider execution

### Objective

Make provider-changing operations crash-safe, idempotent and reconcilable.

### Execution protocol

1. re-read and lock the current case/action/approval;
2. revalidate truth, evidence digest, policy and kill switches;
3. create durable `PENDING` provider intent and deterministic idempotency key;
4. commit before the provider call;
5. claim the intent with a lease;
6. call Razorpay outside the transaction;
7. store the response or explicit ambiguity;
8. verify provider state;
9. attribute the outcome; and
10. reconcile before any retry.

### Action states

`PENDING`, `EXECUTING`, `IN_FLIGHT`, `SUCCEEDED`, `FAILED_RETRYABLE`,
`FAILED_TERMINAL`, `RECONCILIATION_REQUIRED`, `CANCELLED_STALE`, and `VERIFIED`.

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P20-01 | Durable intent before mutation | no direct provider call from request/UI/model |
| P20-02 | Deterministic idempotency key | same exact intent cannot create two actions |
| P20-03 | Lease/claim ownership | concurrent workers cannot execute the same intent |
| P20-04 | Ambiguous response classification | timeout/crash becomes reconciliation-required |
| P20-05 | Provider-reference reconciliation | recover accepted action after application crash |
| P20-06 | Retry only after negative reconciliation | no blind duplicate mutation |
| P20-07 | Bounded retry/terminal classification | explicit retry budget and reason |
| P20-08 | Late-evidence cancellation | stale pending work stops safely |
| P20-09 | Provider verification | acknowledgement alone is not final success |
| P20-10 | Outcome attribution | action, payment and attributed recovery separated |

### Supported actions

Wait/recheck, bounded scheduled retry, payment-link creation, alternate-method
recommendation, manual escalation, stop recovery and cancellation of obsolete
pending recovery. No arbitrary provider operation is allowed.

### Completion gate

The required crash-window test must simulate provider acceptance followed by lost
application persistence and prove reconciliation completes one intent without
creating a duplicate action.

## 15. Phase 21 — Security, resilience and tamper-evident receipts

### Objective

Fail closed under adversarial input, model failure, provider degradation and record
tampering, while retaining enough proof for a reviewer.

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P21-01 | Trusted/untrusted prompt separation | provider/customer text never becomes instruction |
| P21-02 | Strict tool schema and ownership checks | injected tool names/arguments rejected |
| P21-03 | Closed intent types and backend coordinates | prompt cannot invent executable coordinates |
| P21-04 | Secret/PII redaction | prompts, logs, transcripts and UI follow data policy |
| P21-05 | Model failure matrix | timeout/quota/malformed/hallucinated citation/excess steps fail safe |
| P21-06 | Provider degradation matrix | 429/5xx/network/malformed/DB persistence handled distinctly |
| P21-07 | Tamper-evident receipt chain | previous/current hash and canonical serialization |
| P21-08 | Receipt verification service/API | detects changed or missing chain entries |
| P21-09 | Security event audit | rejected injection/ownership/policy attempts recorded safely |
| P21-10 | Invariant monitor | impossible active states alert and block execution |
| P21-11 | Retention and erasure policy | financial proof retained without unnecessary sensitive data |

### Adversarial corpus

At minimum test instructions to ignore policy, fake payment success, increase an
amount, reveal thresholds, use another case/provider resource, invent evidence,
invoke a mutating tool and conceal a conflicting observation.

### Receipt contents

- case/truth/evidence digests;
- model, prompt and tool-registry versions;
- reviewer-safe tool transcript and validated claims;
- candidate ranking and alternatives;
- policy and approval result;
- provider intent, attempts and verification;
- action, payment and attributed recovery outcomes;
- provenance class;
- previous receipt hash and current receipt hash.

External/Merkle anchoring is stretch. A correct local append-only hash chain and
verification path are mandatory.

## 16. Phase 22 — Investigation Room

### Objective

Let a reviewer trace the complete decision without trusting an unexplained AI
paragraph or reading server logs.

### Required sections

| Section | Mandatory information |
| --- | --- |
| Payment Truth | state/version, agreement/conflict, freshness, last verification |
| Evidence Timeline | source, event/observation time, verification, hash, provenance |
| AI Investigation | tools, returned evidence, hypotheses, missing information, abstention/fallback |
| Candidate Actions | ranked alternatives, score components, risk and “why not” |
| Policy | closed verdict, rule results and non-overridable stops |
| Approval | bound versions/digest, approver, expiry and current/stale state |
| Execution | intent, lease/attempt, idempotency reference and reconciliation |
| Outcome | action success, payment success, attributed recovery and safe stops |
| Receipt | chain state, included records and verification action |

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P22-01 | Deep-linkable case investigation route | refresh preserves server truth |
| P22-02 | Clear Test Mode/replay/synthetic provenance | impossible to confuse visually |
| P22-03 | Backend timestamps only | no browser-invented progress/timing |
| P22-04 | Expandable technical proof | readable summary plus exact evidence |
| P22-05 | Alternative-action explanation | winner and exclusions visible |
| P22-06 | Live stale-state handling | new case version marks old view/approval stale |
| P22-07 | Accessible interaction | keyboard, focus, contrast and reduced motion |
| P22-08 | Responsive verification | 1024/1440/1920 and 100%/125% zoom |
| P22-09 | Loading/empty/error/degraded states | no fabricated successful content |
| P22-10 | Receipt verification UI | clear valid/broken/unavailable result |

The interface may be visually impressive, but visual effects must not obscure
uncertainty, provenance, denials or incomplete work.

## 17. Phase 23 — Scenario Lab, evaluation and submission

### Objective

Produce reproducible evidence that ReclaimRail improves investigation and recovery
safety, including failures and non-success paths rather than cherry-picked demos.

### Six hero scenarios

1. failed Test Mode payment to provider-confirmed recovery;
2. client timeout but provider capture preventing a duplicate request;
3. late authorization invalidating approved recovery;
4. duplicate/delayed/out-of-order webhook preserving truth;
5. Gemini timeout or Razorpay 429/5xx degrading safely; and
6. provider acceptance plus application crash reconciled without duplication.

### Four evaluation arms

1. deterministic rules only;
2. legacy one-shot Gemini planner;
3. tool-using Gemini investigator; and
4. investigator plus economic ranker and deterministic policy gate.

All arms receive the same frozen evidence cutoff. No arm may see future outcome
evidence. This temporal split is mandatory to prevent evaluation leakage.

### Mandatory metrics

- payment-truth-compatible conclusion rate;
- unsupported-claim and citation-validity rates;
- unsafe- and duplicate-action rates;
- prompt-injection containment;
- stale-approval prevention;
- tool-call correctness/efficiency;
- abstention quality;
- action success, payment success and attributed recovery;
- eligible/recovered/unresolved/safely-stopped amounts;
- p50/p95 investigation and end-to-end latency;
- token/cost usage and model failure/fallback rate; and
- scenario provenance and denominator.

### Mandatory requirements

| ID | Requirement | Required behavior |
| --- | --- | --- |
| P23-01 | Frozen versioned scenario corpus | stable inputs, expected safety properties and evidence cutoffs |
| P23-02 | Provider-backed and simulated cohorts separated | reports never combine their financial claims |
| P23-03 | Reproducible four-arm runner | same cases, versions and cutoffs |
| P23-04 | Case-level result export | successes and failures retained |
| P23-05 | Honest aggregate report | denominators, intervals and unavailable metrics visible |
| P23-06 | Six hero-scenario harnesses | at least four mandatory before submission; all six target |
| P23-07 | One-command environment verification | dependencies, migrations, services and safe config |
| P23-08 | Demo reset/seed workflow | repeatable without corrupting real proof |
| P23-09 | Final README and architecture | problem, thesis, setup, safety and evidence map |
| P23-10 | Threat model, limitations and evaluation methodology | explicit non-claims and residual risk |
| P23-11 | Five-minute pitch and backup path | dependency failure still demonstrates truthful proof |
| P23-12 | Release gate | clean diff, green CI and fresh end-to-end walkthrough |

### Five-minute pitch sequence

1. explain why payment ambiguity makes naive recovery dangerous;
2. run timeout-but-captured and show duplicate prevention;
3. show Gemini choosing evidence tools and updating hypotheses;
4. show a cited recommendation, alternatives and deterministic policy;
5. execute one safe Test Mode recovery and reconcile it;
6. verify the recovery receipt; and
7. show honest four-arm batch results and limitations.

## 18. Global verification matrix

Every phase runs focused tests during development. Before merge, run all applicable
gates from a clean dependency state.

### Backend

```powershell
cd apps\api
uv sync --locked --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy app
uv run --frozen alembic upgrade head
uv run --frozen alembic check
uv run --frozen pytest -q
```

### Frontend

```powershell
cd ..\web
npm ci --include=optional
npm audit
npm run lint
npm run build
```

If Windows locks a native Node binary, stop the running Next.js/Node process before
re-running `npm ci`. Do not treat subsequent lint/build failures caused by an
incomplete install as source-code defects.

### Required negative/race coverage by the final release

- duplicate and reordered webhook;
- old event and invalid signature;
- missing webhook and provider outage;
- provider result followed by DB failure;
- concurrent truth/investigation/action workers;
- hallucinated/cross-case/future evidence;
- prompt injection and forbidden tool;
- stale and expired approval;
- late authorization during execution;
- provider acceptance/application crash window;
- retry budget, DLQ and controlled replay;
- repeated provider unavailability across worker polls, cooldown windows and restart;
- idempotent unavailable evidence and no truth-version amplification without new facts;
- synthetic provider identifiers blocked from live provider adapters;
- tampered receipt; and
- refresh/restart restoration without invented state.

## 19. Pull-request evidence template

Every phase PR description must contain:

```markdown
## Requirement IDs
- Pxx-...

## Runtime paths
- ...

## Persistence/migrations
- ...

## Failure and race behavior
- ...

## Verification
- focused tests:
- full backend:
- Alembic:
- frontend lint/build:
- audit:
- provider/Test Mode walkthrough:

## Reviewer proof
- API/UI/receipt links or screenshots:

## Deferred/blocked work
- none, or explicit IDs and reasons

## Authorship
- author:
- committer:
```

Do not merge while a required check is pending or failing. After merge, wait for
the final `main` workflow to pass, delete the remote/local phase branch, synchronize
`main`, and record the merge commit here.

## 20. Build and decision log

Append entries; never rewrite old results to look cleaner.

### 23 September 2026 — Phase 15/16 closure

- Phase 15 and Phase 16 corrective completion merged through PR #17.
- Merge commit: `67c950c`.
- Feature commit: `e3a0745`.
- Backend: 669 passed, 1 skipped.
- Alembic upgrade/check passed against PostgreSQL.
- Frontend lint/build passed; npm audit reported zero vulnerabilities.
- Author and committer: `Dhanush R S <dhanushrs981@gmail.com>`.
- Next authorized implementation: Phase 17 only.

### 25 September 2026 — Phase 17 implementation checkpoint

- Implemented the read-only Gemini investigator, durable session/step/hypothesis transcript,
  bounded failure paths, truth-version invalidation and reviewer-safe trace.
- Added deterministic tests for three different tool sequences, abstention, citation ownership,
  prompt leakage, redaction, idempotency and exhausted budgets.
- Reconstruction workspace: Ruff and strict mypy passed; frontend audit/lint/build passed.
- Backend without PostgreSQL: 672 passed and 12 skipped; three existing database integration tests
  were not runnable because the workspace had no configured PostgreSQL service.
- Phase 17 remains in verification until the PostgreSQL, full CI, authorship and merge gates pass.

### 26 September 2026 — Phase 17 core merge and corrective audit

- Phase 17 core runtime merged through PR #19, merge `1912645`, feature `fac8309`.
- PostgreSQL backend: 686 passed, 1 skipped; Alembic upgrade/check passed at `e7a1c2d3f417`.
- Ruff, strict mypy, frontend audit/lint/build and four GitHub CI checks passed.
- Author and committer: `Dhanush R S <dhanushrs981@gmail.com>`.
- Audit found the original live-model comparison had not been executed, the similar-outcomes tool
  was unavailable, and policy summary values were static.
- Corrective closure adds case-backed policy data, privacy-bounded account-scoped outcome aggregates,
  a ten-scenario corpus and a real Gemini benchmark runner.
- The runner separates provider failure from malformed model output, records fail-safe frequency and
  tool efficiency, and refuses to select a model below the locked safety thresholds. Monetary cost is
  labelled unavailable until model pricing is pinned rather than estimated from mutable pricing.
- Phase 17 remains open until the generated real-model report is reviewed and recorded.
- The first live `gemini-3.5-flash` diagnostic returned a sanitized `503 UNAVAILABLE`. Provider
  guidance requires exponential backoff with jitter, so Phase 17B now adds classified transient
  retry, ordered model failover, a hard provider-route time budget and per-attempt benchmark trace.
- Invalid requests, permission failures, malformed turns, citation violations and unsafe tool
  requests are not transport-retried. Exhausting the route produces one labelled fallback; the
  outer investigator does not repeat the whole cascade.

## 21. Priority and scope control

### Mandatory selection-critical path

- Phases 17–20 in full;
- core security and receipt verification from Phase 21;
- complete reviewer trace from Phase 22;
- at least four reliable hero scenarios;
- honest frozen-corpus evaluation; and
- reproducible repository/demo documentation.

### Important after the mandatory core

- full adversarial corpus expansion;
- calibrated action-conditioned recovery probability;
- all six polished scenario automations;
- expanded operational analytics; and
- longer soak/chaos runs.

### Stretch — must not delay submission

- Merkle/external receipt anchoring;
- multi-provider support;
- voice/WhatsApp recovery;
- multiple cooperating agents;
- cross-merchant learning;
- fully trained production probability model; and
- automatic policy generation.

## 22. Time budget

Past estimates are planning ranges, not promises. Re-estimate after each phase using
actual measured work and failures.

| Remaining phase | Expected effort |
| --- | ---: |
| Gate 1A — documentation review and local commit closure | Complete |
| Gate 2 — dependency/access-control stabilization | Complete — `652e440` verified and pushed |
| Phase 17B — investigator closure | included in Phase 17 range below |
| 17 — investigator | 24–30 hours |
| 18 — validation/ranking | 16–20 hours |
| 19 — policy/approval | 12–16 hours |
| 20 — durable execution | 14–18 hours |
| 21 — security/receipts | 14–18 hours |
| 22 — Investigation Room | 18–24 hours |
| 23 — evaluation/submission | 24–32 hours |
| **Remaining total** | **124–163 hours** |

Quality gates determine completion, not elapsed time. If time becomes constrained,
reduce stretch scope, not payment-safety proof.

## 23. Next work order

**Historical 19 November Gate 2 instruction, now superseded:** review and commit
the six-document Gate 2 closure before any Phase 17B work. Gate 1A and Gate 2
were subsequently closed; later owner decisions authorized bounded Phase 17B
diagnostics. This paragraph preserves the old sequence as history, not current
permission or a fresh completion claim.

**Current instruction, 25 November 2026:** review this six-document roadmap
diff first; stage, commit and push only after separate owner authorization.
Preserve all pre-existing spike changes. Phase 17B remains `PARTIAL` with its
live model-selection and submission blocker. Under `DEC-032`, bounded
provider-neutral Phase 18 deterministic claim validation and feasible
coordinate-free intents (P18-01–09, F-14/F-18) are the first implementation
work order after roadmap review. That authorization does not select a model,
count a fallback as Gemini, weaken Phase 17B thresholds or close its blocker.
Phase 19 and later implementation require their own owner decisions and phase
gates. Follow the 25 November sequence above; stop for owner review at each
phase boundary. A further live model evaluation needs a separate bounded owner
decision, and one complete evaluation ends provider search/prompt tuning until
another owner decision.
