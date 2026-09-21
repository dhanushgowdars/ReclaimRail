# ADR-0004: Persist Provider Intent Before External Execution

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

The database and Razorpay cannot participate in one atomic transaction. A process
can crash after Razorpay accepts an action but before local success is committed.
Blind retry can therefore create duplicate recovery resources or customer harm.

## Decision

ReclaimRail will commit a durable action intent and deterministic idempotency key
before the provider call. Ambiguous calls become `IN_FLIGHT` or
`RECONCILIATION_REQUIRED`. Reconciliation checks provider state before any retry.

## Consequences

- Every external action has a prior auditable local record.
- Crash recovery prefers provider reconciliation over repetition.
- Workers require per-case concurrency protection and explicit action states.
