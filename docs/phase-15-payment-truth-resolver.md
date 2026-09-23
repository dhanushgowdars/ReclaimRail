# Phase 15 — Payment Truth Resolver

- **Branch:** `phase-15/payment-truth-resolver`
- **Baseline:** `afd99baf8d836ffb988fbb4da2b013dd6786a921`
- **Status:** Complete and merged; PostgreSQL-backed verification passed

## Problem

A client timeout, missing webhook or application error is not proof that money failed
to move. Recovery based on that assumption can create duplicate payment requests.
ReclaimRail therefore resolves a versioned truth from immutable evidence before a
failed projection remains recovery-eligible.

## Delivered

- Append-only `payment_evidence` persistence with source identity, provider/source
  reference, event and observation times, freshness, verification state and SHA-256
  integrity.
- Append-only `payment_truth_snapshots` with per-payment versions, cited evidence,
  conflict codes, deterministic evidence digest and resolver version.
- Deterministic resolution for confirmed, failed, pending, unknown, conflicting,
  late-authorized, active-recovery, recovered and manual-investigation states.
- Fail-closed handling for unverified evidence, stale evidence, source disagreement
  and amount/currency/ownership identity mismatches.
- Signed payment webhook integration: every normalized lifecycle transition writes a
  verified evidence fact, cites the original stored payload SHA-256 and resolves truth
  in the same database transaction.
- Recovery eligibility is now derived from both the payment projection and resolved
  truth. Unknown, conflicting and successful outcomes cannot remain eligible.
- Runtime collection for signed webhooks, provider payment state, provider order
  state, the merchant projection, Payment Lab, recovery cases/actions, recovery
  links and reconciled recovery outcomes.
- Ledger proof includes signature status, normalized fields, freshness,
  reliability classification and an explicit provider-unavailable reason.
- A new truth version increments the linked case version and supersedes pending
  plans, actions and approvals before they can execute against stale evidence.
- Idempotent evidence identity and snapshot suppression prevent webhook replay from
  creating duplicate truth versions.

## Truth rules

| Evidence | Resolved truth | Recovery implication |
| --- | --- | --- |
| Verified failure only | `PAYMENT_FAILED` | Eligible if the projection is also failed |
| Created/pending only | `PAYMENT_PENDING` | Do not recover |
| No fresh verified evidence | `OUTCOME_UNKNOWN` | Pause and investigate |
| Authorized/captured/refunded | `PAYMENT_CONFIRMED` | Stop recovery |
| Failure followed by explicit late authorization | `LATE_AUTHORIZATION` | Stop recovery |
| Confirmed and failed sources disagree | `SOURCE_CONFLICT` | Fail closed |
| Identity evidence reports a mismatch | `SOURCE_CONFLICT` | Fail closed |
| Recovery is executing | `RECOVERY_ALREADY_ACTIVE` | Do not duplicate |
| Recovery payment is verified | `RECOVERY_CONFIRMED` | Close as recovered |

## Compatibility

The existing payment state machine remains authoritative for lifecycle ordering and
late-authorization detection. The truth layer records and interprets evidence; it
does not let an LLM select facts, amounts, customer identity or provider resources.
The Gemini planner is intentionally unchanged in this phase.

## Verification gate

- Focused truth, payment projection and state-machine tests.
- Full API test suite against migrated PostgreSQL.
- Ruff formatting and lint.
- Strict mypy.
- `alembic upgrade head` followed by `alembic check`.
- Existing frontend lint and production build, despite no frontend source changes.

## Phase 16 handoff

Phase 16 adds provider polling evidence, missing-event detection, reconciliation
jobs and explicit handling of duplicate, delayed and out-of-order delivery across
webhook and provider API sources.

## Closure

The remaining evidence-source and reconciliation acceptance requirements were
completed and verified with Phase 16. The combined gate reported 669 passed and
1 skipped, with Alembic upgrade/schema check, frontend lint/build and npm audit
passing before merge.
