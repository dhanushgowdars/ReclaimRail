# ADR-0005: Separate Simulated, Test Mode and Attributed Recovery

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

Provider API success does not prove that a customer completed payment, and payment
success does not by itself prove that ReclaimRail caused the recovery. Synthetic
evaluation can measure safety but cannot be presented as real recovered revenue.

## Decision

ReclaimRail will report action success, payment success and attributed recovery as
separate metrics. Every result identifies whether it is synthetic, simulated,
Razorpay Test Mode or production. Missing denominators remain unavailable.

## Consequences

- Evaluation claims remain reproducible and defensible.
- Model and policy comparisons use the same declared corpus and denominators.
- The demo can show technical proof without overstating business outcomes.
