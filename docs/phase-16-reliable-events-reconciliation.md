# Phase 16 — Reliable Events and Reconciliation

- **Status:** Complete and merged
- **Merge:** PR #17 / `67c950c`
- **Verification:** 669 passed, 1 skipped; Alembic upgrade/check, frontend
  lint/build and npm audit passed

## Result

Signed webhooks and server-side Razorpay reads feed the same deterministic state
machine and versioned truth resolver. Browser callbacks never establish truth, and
Gemini never decides chronology, source precedence or execution authority.

## Reliability controls

| Failure mode | Durable behavior |
| --- | --- |
| Invalid HMAC | Delivery is rejected and recorded without projection |
| Duplicate event | Canonical event and transition IDs remain idempotent |
| Reordered event | Regression is stored as ignored and cannot roll state backward |
| Event older than seven days | Signed payload remains stored but is not projected |
| Unsupported event | Canonical event is retained and safely skipped |
| Missing webhook | Reconciliation fetches Razorpay Order Payments server-side |
| Provider outage | DNS/network, connect timeout, read timeout, 429, 4xx, 5xx and malformed responses are distinct |
| Database failure after provider response | Reported separately as an evidence-persistence failure; no false success |
| Repeated provider outage | Batch circuit opens after three consecutive provider failures |
| Repeated consumer failure | Configured retry budget ends in the DLQ |
| DLQ replay | One entry, one named operator, one reason and one durable replay audit |
| Outbox retry | Exponential backoff includes bounded jitter and a maximum attempt count |

## Reconciliation loop

The supervised Payment Lab recovery worker owns both:

1. global reconciliation for stale, pending, unknown, conflicting or manual-review
   payment truth with a known Razorpay order; and
2. pre-attempt Payment Lab order polling for runs that do not yet have a payment
   projection.

Provider results become deterministic `provider-api:{payment}:{status}` canonical
events. New evidence creates a new truth version, increments the case version and
invalidates stale plans/actions/approvals. A provider timeout is stored as evidence
and resolves to manual investigation rather than being guessed as payment failure.

## Reviewer proof

The case detail API and UI expose:

- truth state, version, resolver and evidence digest;
- cited evidence IDs and conflict codes;
- source record, fact, verification and signature status;
- reliability, freshness, normalized fields and raw-content SHA-256;
- event source, delivery classification, latency and state-machine result.

## Verification gates

- Deterministic truth scenario tests.
- Event age, ordering and provenance tests.
- Provider taxonomy, retry jitter, circuit and retry-budget tests.
- Controlled replay and duplicate replay rejection tests.
- Backend formatting, lint, strict typing and full test suite.
- Alembic upgrade/schema check against PostgreSQL.
- Frontend lint, production build and npm audit.
