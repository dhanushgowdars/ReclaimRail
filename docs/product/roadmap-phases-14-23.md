# ReclaimRail Locked Roadmap — Phases 14–23

- **Status:** Locked
- **Date:** 2026-09-22
- **Baseline:** `67c950c` (Phases 15 and 16 merged)
- **Product:** Evidence-Grounded Payment Truth and Recovery Control Plane

> The detailed implementation source of truth is
> [`MASTER-EXECUTION-PLAN.md`](MASTER-EXECUTION-PLAN.md). That document defines
> stable requirement IDs, runtime deliverables, tests and phase exit gates. This
> file remains the compact roadmap.

## Thesis

When payment systems disagree, ReclaimRail establishes payment truth, lets an AI
investigator gather and challenge evidence, permits recovery only through
deterministic policy and fresh provider state, executes idempotently, verifies the
provider outcome and produces an auditable recovery receipt.

The existing Payment Lab, signed webhooks, policy, approvals, recovery links, late
authorization protection, reconciliation, Outcome Ledger and audit surfaces remain
part of the product.

## Delivery order

| Phase | Scope | Required result |
| --- | --- | --- |
| 14 | Safety invariants and contracts | Typed boundaries and tests exist without changing runtime behaviour |
| 15 | Payment Truth Resolver | Versioned truth is derived from stored provider, webhook, merchant and recovery evidence |
| 16 | Reliable events and reconciliation | Duplicate, delayed, missing or reordered events cannot duplicate recovery |
| 17 | Gemini evidence investigator | The model chooses bounded read-only tools and may abstain; deterministic answers are not leaked in prompts |
| 18 | Evidence validation and action ranking | Every claim is cited; AI emits a coordinate-free intent; actions are economically ranked |
| 19 | Policy and state-bound approval | Latest truth and policy authorize; new evidence invalidates stale approval |
| 20 | Durable provider execution | Intent is committed before provider mutation; ambiguous results reconcile before retry |
| 21 | Security, resilience and receipts | Injection/model failures fail closed; the decision and outcome are tamper-evident |
| 22 | Investigation Room | A reviewer can trace evidence, hypotheses, alternatives, policy, execution and outcome |
| 23 | Scenario Lab, evaluation and submission | Real and simulated results are separated; hero scenarios and four-arm evaluation are reproducible |

## Delivery checkpoint

- Phase 14: complete and merged.
- Phase 15: complete and merged; corrective evidence-source completion was included
  and verified with Phase 16.
- Phase 16: complete and merged through PR #17 (`67c950c`). Backend tests reported
  669 passed and 1 skipped; PostgreSQL migrations/schema check, frontend lint/build
  and npm audit passed.
- Phase 17: implementation complete on its branch; PostgreSQL, CI, authorship and merge verification
  remain before closure. P17-01 through P17-16 are mapped in the Phase 17 acceptance matrix.
- Phases 18–23: pending; their scope remains locked below.

## Hero scenarios

1. Failed Test Mode payment to provider-confirmed recovery.
2. Client timeout but provider capture, safely preventing a duplicate request.
3. Late authorization invalidating an approved recovery action.
4. Duplicate, delayed and out-of-order webhooks preserving correct truth.
5. Gemini timeout or Razorpay `429/5xx` degrading safely.
6. Provider success followed by application crash reconciling without duplication.

## Evaluation arms

1. Deterministic rules only.
2. Current one-shot Gemini planner.
3. Tool-using Gemini investigator.
4. Investigator plus economic ranker and deterministic policy gate.

Action success, payment success and attributed recovery are separate metrics. Synthetic,
simulated and Razorpay Test Mode results remain labelled. Missing denominators remain
unavailable rather than becoming invented zeroes.

## Execution discipline

- Work on one phase at a time from a green baseline and dedicated branch.
- Write tests and documentation with the implementation.
- Do not mark a phase complete from UI screenshots alone.
- Do not start frontend presentation before its backend evidence exists.
- Preserve a full tool/action transcript, not private model chain-of-thought.
- Run focused checks during development and the full API/frontend gate before completion.
- Update the roadmap checkpoint and build log before beginning the next phase.
- Treat Merkle anchoring, multiple providers, voice, multiple agents and cross-merchant
  learning as stretch work until the selection-critical path passes.

The complete safety contract is defined in [`../INVARIANTS.md`](../INVARIANTS.md).
