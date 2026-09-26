# Phase 17 — Gemini Evidence Investigator

## Status

Implementation complete on the Phase 17 branch; PostgreSQL migration/integration and final CI
verification remain required before merge. This document does not declare Phase 17 merged.

## Delivered runtime

- A versioned registry of 11 read-only evidence tools. Unknown tools, mutation-shaped requests,
  extra arguments, cross-case IDs and observations after the session cutoff fail closed.
- A durable investigation session, ordered tool transcript and versioned hypothesis ledger.
- A bounded loop with tool-call, model-retry, token and wall-clock budgets.
- Strict structured model turns: call one tool, complete with citations, or explicitly abstain.
- Citation validation against evidence IDs returned earlier in the same session.
- An isolated Gemini adapter using JSON-schema output with automatic function calling disabled.
- Recursive removal of secret/contact fields before model-visible tool output.
- Idempotent ownership per `(recovery_case_id, case_version)` and stale-version invalidation when
  payment truth changes.
- Shadow-mode wiring beside the existing planner. Investigation failure cannot block deterministic
  recovery, and the investigator has no action/execution tool.
- A reviewer-safe API and minimal case-page trace containing versions, cutoff, steps, hypotheses,
  evidence IDs, budget consumption, terminal state and labelled fallback.

## Authority boundary

The investigator may read and explain persisted evidence. It cannot create a payment link, contact a
customer, approve an action, change payment truth or invoke a provider mutation. The existing
deterministic policy remains authoritative. Provider reconciliation persists normalized observations
to `payment_evidence`; investigator tools read that ledger rather than exposing an unledgered raw
provider response to Gemini.

## Different evidence paths proved

The service contract suite executes these distinct model-selected sequences:

1. `get_truth_snapshot` → `get_verified_webhooks`;
2. `get_provider_payment` → `get_internal_payment` → `get_recovery_history`;
3. `get_provider_order` → `get_route_health` → `get_payment_link_status`.

These are provider-adapter scripts for deterministic testing, not claims about production model
quality. Live Gemini model comparison belongs to the frozen evaluation corpus and must record real
latency, token, citation and abstention results before changing the configured model.

## Persistence

Migration `e7a1c2d3f417` adds:

- `recovery_investigation_sessions`;
- `recovery_investigation_steps`; and
- `recovery_investigation_hypotheses`.

The session unique constraint prevents duplicate investigations for the same case version. A newer
truth version increments the recovery-case version and marks a running older investigation
`failed_safe` with `superseded_by_new_evidence`.

## Measured verification in the reconstruction workspace

- Ruff format/check: passed for 249 files.
- strict mypy: passed for 119 source files.
- Phase 17 focused tests: passed.
- full backend without a configured PostgreSQL URL: 672 passed, 12 skipped; the three existing
  PostgreSQL integration tests could not start because this workspace has no Docker/PostgreSQL.
- Alembic graph: one head, `e7a1c2d3f417`, directly after `d3e6a9b4c201`.
- frontend install/audit/lint/production build: passed; zero npm vulnerabilities.

The final completion record must replace the environment-limited backend line with the result from
the repository's PostgreSQL gate, then record the PR and merge commit.

## Required final commands

From `apps/api` with the local services and `.env` configured:

```powershell
uv sync --locked --group dev
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy app
uv run --frozen alembic upgrade head
uv run --frozen alembic check
uv run --frozen pytest -q
```

From `apps/web`:

```powershell
npm ci --include=optional
npm audit
npm run lint
npm run build
```
