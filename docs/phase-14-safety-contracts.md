# Phase 14 — Safety Invariants and Contracts

- **Branch:** `phase-14/safety-invariants-contracts`
- **Baseline:** `8a7300b7bde387d5a295235b7ac02b3f31169911`
- **Status:** Implemented locally; PostgreSQL-backed CI verification pending

## Delivered

- Twenty-five architectural invariants covering payment truth, AI authority, policy,
  approval, provider execution and honest evaluation.
- Provider-neutral typed contracts for payment evidence, versioned truth, cited AI
  claims, investigation hypotheses, coordinate-free recovery intent, deterministic
  policy decisions, state-bound approvals, durable provider attempts and chained
  recovery receipts.
- ADR-0002: versioned payment truth.
- ADR-0003: AI authority boundary.
- ADR-0004: durable provider execution.
- ADR-0005: honest recovery evaluation.
- Focused contract tests, including negative tests for missing citations, invalid
  hashes, source conflicts without codes, unproved hypotheses, stale approval shape
  and unverified provider actions.
- Locked repository roadmap for Phases 14–23; the earlier roadmap is retained as
  historical delivery context.

## Compatibility

This phase deliberately introduces no database migration and changes no live recovery
runtime. Later phases will adopt the contracts incrementally.

## Verification

- `ruff check app tests`: passed.
- New contract file under strict `mypy`: passed.
- Focused recovery/contract tests: **56 passed**.
- Full API suite: **622 passed, 12 skipped, 3 environment-blocked**. The three blocked
  integration tests require `RECLAIMRAIL_DATABASE_URL`; Docker/PostgreSQL are not
  available in the audit environment. They are the same database-configuration gate
  observed at the baseline and do not exercise Phase 14 contracts.
- Frontend lint: passed.
- Frontend production build: passed after moving aside a corrupted generated
  Turbopack cache; no frontend source changed.

## Phase 15 handoff

Phase 15 will persist `PaymentEvidence` and `PaymentTruthSnapshot`, implement the
deterministic truth resolver, and connect it to existing payment projection and
reconciliation without yet changing the Gemini planner.
