# Phase 15–16 Acceptance Matrix

This file is the merge gate. A feature is complete only when its runtime path and
test/proof path both exist.

## Phase 15 — Payment Truth Resolver

| Locked requirement | Runtime evidence | Verification |
| --- | --- | --- |
| Razorpay payment state | Provider API canonical events and `provider_payment_api` ledger facts | provider reconciliation and projection tests |
| Razorpay order state | Payment Lab order metadata recorded as `provider_order_api` | linked-runtime evidence tests/integration gate |
| Verified webhook | Raw-body HMAC intake and signature-marked evidence | webhook endpoint, ingestion and truth tests |
| Merchant/internal state | Versioned `PaymentAttempt` facts | projection integration gate |
| Payment Lab state | `payment_lab` ledger facts with provenance | provider verification tests |
| Previous recovery actions | Recovery case version/status facts | truth service integration gate |
| Reconciliation results | `reconciliation` facts and outcome projection | reconciliation tests |
| Recovery-link status | `recovery_link` fact and reconciled outcome | recovery outcome integration gate |
| Evidence ID/source/times/hash | `PaymentEvidenceRecord` | model, service and API tests |
| Signature/normalized/freshness/reliability | Dedicated ledger columns | migration, truth and case-detail tests |
| Nine truth states | `PaymentTruthState` and deterministic resolver | truth scenario matrix |
| Failed payment | verified `failed` → `PAYMENT_FAILED` | resolver test |
| Captured payment | captured/paid → `PAYMENT_CONFIRMED` | resolver/projection tests |
| Authorized, not captured | authorized → `PAYMENT_PENDING` | resolver test |
| Network timeout but captured | provider capture overrides uncertainty | provider reconciliation integration gate |
| Missing webhook | provider poll synthesizes canonical event | verification/reconciliation tests |
| Duplicate/out-of-order | idempotency plus monotonic state machine | projection tests |
| Conflicting sources | `SOURCE_CONFLICT` with conflict code | resolver test |
| Provider unavailable | durable unavailability evidence → manual investigation | resolver/reconciliation tests |
| Late authorization | explicit `LATE_AUTHORIZATION`; recovery stopped | projection integration gate |

## Phase 16 — Reliable Events and Reconciliation

| Locked requirement | Runtime evidence | Verification |
| --- | --- | --- |
| HMAC and invalid signature | webhook route + rejected delivery | endpoint tests |
| Idempotency/duplicates/order | canonical uniqueness + state machine | ingestion/projection tests |
| Event-age validation | seven-day fail-closed policy | processor/reliability tests |
| Unsupported storage | canonical event marked processed/skipped | processor test |
| DLQ and retry budget | Redis DLQ after permanent error or exhausted attempts | consumer tests |
| Controlled replay/audit | single-entry replay service + durable audit table | replay tests |
| Provider error taxonomy | explicit seven-kind enum | Razorpay provider tests |
| Provider response/DB failure | `ProviderEvidencePersistenceError` | reconciliation path |
| Stale/conflicting reconciliation | global candidate scan + provider fetch | reconciliation tests |
| New truth invalidates old work | case version bump, plan supersede, action cancel, approval expiry | truth service/integration gate |
| Transactional outbox | existing database outbox | outbox tests |
| Locks/leases | row locks and skip-locked worker claims | service/integration tests |
| Backoff/jitter/budget | bounded exponential delay and max attempts | outbox/consumer tests |
| Circuit breaker | three consecutive provider failures open batch circuit | reconciliation test |
| Worker heartbeat | supervised worker heartbeat | worker supervision tests |
| Reviewer proof | truth/evidence/event provenance in case API and UI | endpoint, lint and build gates |

## Merge gate

- No unresolved formatting, lint or strict typing errors.
- Full backend suite passes with PostgreSQL configured.
- Alembic upgrade and `alembic check` pass.
- Frontend lint/build and `npm audit` pass.
- Git author and committer are the project owner; generated patch carries no author metadata.
