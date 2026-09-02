# ReclaimRail completion roadmap

Status: active source of truth  
Baseline: merged `main` at PR #12 / `4721195`  
Last updated: 30 August 2026

## How to use this roadmap

This document is the project completion checklist. Before changing a feature:

1. Identify the requirement IDs affected.
2. Implement the smallest coherent slice that preserves the recovery contract.
3. Add or update automated tests.
4. Run the relevant verification commands and record the result in the pull request.
5. Mark a requirement complete only after its stated acceptance evidence exists.

Passing unit tests alone do not make a user-facing feature complete. A provider-backed
claim also needs the stated Test Mode or provider evidence. Do not silently replace a
real path with a simulator to make a demo easier.

## Product promise

> ReclaimRail is an incident-aware, policy-bounded, auditable recovery control plane
> for Razorpay payment failures.

The recovery loop is:

`Detect → Diagnose → Propose → Decide → Approve/Execute → Reconcile → Stop unsafe recovery → Measure → Audit`

Gemini may propose. Deterministic policy decides what is permitted. Signed provider
evidence, not browser callbacks, determines payment state and financial outcome.

## Non-negotiable rules

- Keep Razorpay hosted checkout for payment entry. Never collect provider passwords,
  PINs, OTPs, or card secrets.
- Use only provider-backed Test Mode claims in the live demonstration. Clearly label
  replay and synthetic drills; neither creates recovered money.
- A payment link, notification API acceptance, browser success callback, or AI proposal
  is not recovered revenue. Count a recovery once only after provider reconciliation.
- Recovery sends require permitted policy, valid original-state recheck, appropriate
  consent, and any required human approval.
- A late original authorization must revalidate and stop/cancel obsolete recovery work
  when needed to reduce duplicate collection risk.
- AI confidence is not a guarantee that a customer will pay. Never invent AI tool calls,
  provider delivery, timings, incident evidence, or completed stages.
- Do not force-push, delete lockfiles, or apply broad rebase/cherry-pick ranges to hide
  integration problems. Preserve the known merged baseline and make scoped changes.

## Current evidence

Already present in merged work:

- Real Razorpay Test Mode order/check-out and signed webhook-driven workflow.
- Backend recovery cases, policy bounds, approvals, outcome handling, incident context,
  late-authorization compensation, workers, audit foundations, and tests.
- Gemini structured planner with deterministic fallback and trace data.
- Real Resend direct recovery email path, manually demonstrated as working.
- Custom amount input on the API and frontend (with a guided preset).
- Server-polled live-run API. Existing tests, CI, and local reported build/lint results
  are strong foundations, not a blanket production certification.

Known gaps to close:

- The frontend ignores several live API fields, especially the full AI trace, approval,
  worker state, waiting reason, and useful business-state labels.
- Agent timing is not yet honest enough for per-phase timing presentation.
- Custom amount and controlled test-email settings are currently incompatible.
- SMS delivery feasibility/receipt proof is not yet validated for the configured account.
- Email retries need a stable provider idempotency key and receipt-state treatment.
- No dedicated reproducible batch evaluation/reporting harness has been verified.
- The current visual experience is to be replaced, not cosmetically patched.
- Judge-facing setup, architecture, evidence, limitations, and five-minute demo docs are incomplete.

## Implementation log

- **30 August 2026 — Slice 12A in progress:** the live API contract now includes
  business state, waits, worker diagnostics, approval, AI trace and recorded
  executor timing. Agent and provider-action durations are emitted only when both
  persisted bounds exist. Custom amounts can opt into the consented demo-email
  route, and Resend uses a stable per-action idempotency key. The first replacement
  live command surface renders this persisted evidence instead of browser-timed
  stages. Focused API tests are passing; frontend build verification remains due in
  the developer environment with its locked dependencies installed.

## Requirements register

| ID | Requirement | Status | Completion evidence |
| --- | --- | --- | --- |
| R01 | Live stages come only from backend evidence | Partial | Refresh/reconnect tests and a fresh provider run show no client-invented stages |
| R02 | Clear product-level live experience | Planned | One readable Detect-to-Audit flow at desktop/mobile target sizes |
| R03 | Full AI trace is understandable | In progress | Live UI shows model/fallback, assessment, recommendation, evidence, confidence disclaimer and policy result |
| R04 | Deterministic policy is visible and authoritative | Partial | Allowed/waiting/blocked/review paths show exact explanation and guards |
| R05 | Real custom payment amount | Partial | Chosen amount stays consistent from order through message, link and outcome |
| R06 | Consented real email recovery | Partial | A fresh Test Mode run stores one provider request/result with duplicate-safe retry tests |
| R07 | Consented real SMS recovery | Planned / account gate | Approved recipient receives link; request/delivery evidence is honestly represented |
| R08 | Notification status is truthful | Planned | Queued, accepted, delivered where available, failed and unknown are distinct |
| R09 | Real AI and phase timings | Planned | Persisted distinct start/end/wait timestamps; historical unknown is never fabricated |
| R10 | Human approvals are contextual and revalidated | Partial | Expired/changed-evidence approval cannot authorize stale execution |
| R11 | Incident-aware recovery is visible | Partial | Real incident evidence or labelled drill causes safe wait/replan |
| R12 | Late authorization safety is demonstrated | Partial | Race test and provider/audit evidence show safe stop/compensation |
| R13 | Recovery message/link evidence is clear | Planned | UI shows masked recipient, amount, channel, provider ID/status, link state and expiry |
| R14 | Case, review, rail, ledger and audit views are coherent | Planned | Views are populated by APIs and each metric links to evidence/provenance |
| R15 | Batch recovery result is reproducible | Planned | Stable cohort report includes every case, failure, pending, review and stop |
| R16 | AI is evaluated against a baseline | Planned | Same-input comparison shows diagnosis, action suitability, safety blocks, fallback and latency |
| R17 | Worker/connection health is visible | Partial | Stalled/waiting states have last evidence, responsible worker and next safe action |
| R18 | Accessibility and responsiveness | Planned | Keyboard, reduced-motion, contrast, 1024/1440/1920 and 100/125% zoom checks |
| R19 | Submission proof package | Planned | Reproducible README, architecture, evaluation, limitations and five-minute demo script |
| R20 | Regression and release discipline | Active | Clean diff, targeted tests, full API/frontend CI and fresh end-to-end Test Mode verification |

## Delivery order

### Slice 12A — Evidence contract and truthful instrumentation

Goal: make the backend/API data safe to present as a live product.

- Align TypeScript live-run contract with `business_state`, `state_label`, waiting,
  worker diagnostics, full `ai_trace`, approval, and financial terminal fields.
- Persist real agent execution start/completion/failure timing. Separate queue delay,
  model work, policy/stabilization wait, provider wait, and customer wait.
- Expose last evidence timestamp, wait reason/deadline, responsible worker and stalled
  reason without leaking secrets.
- Define notification attempt/receipt states and idempotency rules.
- Add API/service tests for normal, wait, stop, approval, timeout, fallback and
  unknown-evidence cases.

Exit gate: R01, R04, R09 and R17 have tests; UI can display only trustworthy data.

### Slice 12B — Customer recovery and AI decision proof

Goal: demonstrate the recovery action the customer can actually take.

- Unify guided/custom amount, payment method, approved contact and consent controls.
- Retain a convenient guided preset but allow bounded selected amounts before order creation.
- Preserve existing Resend email path; add stable idempotency and durable message state.
- Reuse existing Razorpay notification support for SMS first. Test actual account/recipient
  capability before claiming delivery. Do not add a paid provider without an explicit decision.
- Add the AI decision record: evidence supplied, diagnosis, recommendation, policy verdict,
  guardrails, actual model or fallback, and concise operator explanation.

Exit gate: one fresh selected-amount Test Mode recovery has consented notification evidence,
the actual link, and truthful outcome state. SMS is marked complete only after its own account
delivery gate passes.

### Slice 12C — Full live recovery experience rebuild

Goal: replace the old dashboard/card experience with an evidence-first product experience.

- New visual system: strong hierarchy, readable type, status text/icons, accessible color,
  deliberate navigation and an intentional product mark.
- Main canvas: amount/run/Test Mode/provenance, current stage, live elapsed time, concise
  explanation and one next safe action.
- Decision room: AI proposal alongside deterministic policy; technical evidence is expandable.
- Customer message panel: real link/recipient/channel/status, never a fake SMS bubble.
- Timeline: real timestamps, catch-up state when events arrive behind checkout, no fake delay.
- Live versus replay versus synthetic provenance is unmissable. Replay has controls; live does not
  pretend completed persisted events are currently running.
- Refresh restores the live run; inspecting history pauses auto-follow and supports resume.

Exit gate: R02, R03, R08, R13 and R18 pass browser/visual checks and a judge can understand
the entire loop without a verbal backend explanation.

### Slice 12D — Operational control plane

Goal: make the project look like a merchant recovery product, not a single demo page.

- Recovery Cases: status, amount, risk, evidence and next safe action.
- Human Reviews: reason, threshold, expiry, version, decision and revalidation.
- Rail Intelligence: incident sample/context/affected work with explicitly synthetic drill mode.
- Command Center: at-risk, verified recovered and prevented-duplicate figures only where backed
  by data; meaningful queue/funnel/rail health, not placeholder metrics.
- Audit & Controls: model/prompt/policy/evidence versions, action history and safe worker health.

Exit gate: R10, R11, R12 and R14 have end-to-end normal and denial/stop walkthroughs.

### Slice 12E — Measured Track 3 proof

Goal: prove recovery and safety across a declared batch.

- Create a reproducible cohort runner/report with stable case IDs, provenance and results.
- Keep provider-backed Test Mode cases and deterministic synthetic cases separate.
- Include all eligible, recovered, failed, pending, reviewed, escalated and stopped cases in
  the denominator. Do not cherry-pick success.
- Report eligible amount, provider-verified recovered amount, rate, unresolved balance,
  safe stops, escalation/fallback, and median/p95 decision latency.
- Evaluate deterministic baseline and AI-plus-policy on identical labelled scenarios.

Exit gate: R15 and R16 produce a repeatable case-level report. Test Mode remains clearly
labelled as non-production money.

### Slice 12F — Release, judge proof and submission

Goal: make the project easy to assess and reproduce.

- Full API/frontend regression, browser/accessibility checks, safe configuration and clean
  README.
- Architecture diagram, track mapping, evaluation methodology, provider/synthetic boundary,
  limitations and security/consent notes.
- Five-minute demo: recover, reason under an incident/uncertain state, protect against late
  authorization, then show batch proof.

Exit gate: R19 and R20 pass. The submission tells the truth even when a dependency fails.

## Active delivery order (locked 2026-09-02)

This sequence is the implementation checklist for the current branch series. A later phase must
not erase or bypass evidence completed in an earlier phase.

| Delivery phase | Scope | Exit gate |
| --- | --- | --- |
| 12D — truthful live-run hardening | Restore an active run after refresh; verify process identity before stopping Windows PIDs; preserve numbered evidence stages; show immutable agent/policy/provider/outcome facts; remove false timing and ambiguous audit labels; verify both automatic and protected-review amounts. | Fresh ₹3,499 recovery and high-value approval walkthrough both pass without invented state. |
| 13 — application routes and navigation | Replace placeholder navigation with separate Command Center, Recovery Cases, Human Reviews, Outcome Ledger, Safety Controls and Rail Intelligence routes while preserving Live Demo and case evidence deep links. | Every navigation item has a real route, loading/error/empty state and stable refresh/deep-link behavior. |
| 14 — recovery operations | Build case list/filter/search/detail workflows, human-review queue and decision flow, expiry/version/revalidation handling, and incident/rail context backed by persisted evidence. | Normal, approval, denial, expiry and stale-decision paths pass end to end. |
| 15 — outcomes and safety | Build the provider-backed outcome ledger, duplicate-collection prevention, late-authorization stop evidence, policy/control history and safe operational health views. | Recovered revenue is counted only after reconciliation; stop and duplicate paths are demonstrable. |
| 16 — reliability and end-to-end proof | Cover duplicate/out-of-order webhooks, restarts, replay, polling recovery, accessibility/responsive layouts, failure/fallback behavior and full API/frontend regression. | CI and fresh-machine walkthrough are green, including degraded dependency behavior. |
| 17 — submission and demo | Finish architecture/track mapping, evaluation report, limitations/security notes, reproducible setup and the five-minute recover/reason/protect/measure demo. | A reviewer can reproduce and judge the complete Track 3 claim without private explanation. |

The current implementation target is Phase 12D. Phase 13 begins only after both Phase 12D live
walkthroughs pass.

## Required verification matrix

| Change area | Minimum verification |
| --- | --- |
| API/service | focused `uv run pytest`, then full API suite before merge |
| Frontend | `npm ci`, `npm run lint`, `npm run build`; add component/browser tests where available |
| Payments/messaging | Test Mode/provider evidence, no real-money claim, allowed recipient/consent checks |
| AI | Gemini success, timeout/fallback, malformed output, policy-block and safe explanation tests |
| Safety/races | duplicate webhook, out-of-order event, concurrent worker, late auth, expired approval/link |
| Visual | 1024/1440/1920 layouts, 100%/125% zoom, keyboard, contrast and reduced-motion review |
| Release | clean status, review diff, green CI, fresh complete flow and updated documentation |

## Demo scenes to preserve

1. **Recover:** signed failure → AI/policy → one consented message → customer uses real Test
   Mode recovery link → provider-confirmed outcome.
2. **Reason:** verified incident or clearly labelled incident drill → wait/replan/approval rather
   than blind retries.
3. **Protect:** late original authorization → obsolete recovery action is safely stopped and the
   audit explains why.
4. **Measure:** batch report includes success and non-success paths, with provenance.

## Out of scope until the gates above pass

- Generic chatbot, autonomous financial decision maker, fake agent streaming, arbitrary multi-agent
  theatrics, production payments, credential automation, WhatsApp/voice expansion, unrelated
  subscription features, framework migration, or real-time infrastructure solely for appearance.

## Change log

- 2026-08-30: roadmap created after merged Phases 8–11. The first frontend evidence-contract/
  AI-decision-room slice is in local progress and must be verified before it is considered done.
- 2026-08-30: Slice 12A implementation checkpoint completed locally: custom Test Mode amounts,
  consented direct-email recovery notification, idempotent Resend request handling, persisted
  agent timing bounds, action-channel evidence, and an evidence-first live command screen are
  implemented. 46 focused API tests pass; `npm run lint` and the production Next build pass.
  Browser/visual verification remains required before this checkpoint is ready to commit.
