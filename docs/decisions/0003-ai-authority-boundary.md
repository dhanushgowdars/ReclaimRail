# ADR-0003: Limit AI to Evidence Investigation and Typed Intent

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

An LLM is useful for selecting evidence, comparing hypotheses and explaining
context, but it cannot be trusted to choose authoritative financial coordinates or
authorize money movement.

## Decision

The model may call bounded read-only tools and propose a `RecoveryIntent`. It may
reference evidence, claims, an action type and execution timing. Trusted backend
code resolves amounts, customers, provider resources and policy. Deterministic
policy and, where required, a state-bound human approval authorize execution.

## Consequences

- Model hallucinations cannot directly alter money or customer coordinates.
- Every accepted model claim must be validated against stored evidence.
- The model may abstain without weakening the safe deterministic path.
