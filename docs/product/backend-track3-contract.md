# ReclaimRail Track 3 backend contract

Status: locked for implementation on 2026-08-28.

## Product claim

ReclaimRail is an incident-aware, policy-bounded revenue-recovery control plane. It turns
verified payment failures into safe recovery actions, routes uncertainty to a human,
stops unsafe collection, and measures provider-confirmed outcomes with an auditable chain
of evidence.

## Authority boundary

- Razorpay-signed webhooks and server-side reconciliation are financial truth.
- Gemini may diagnose and rank allowed interventions; it cannot execute actions, change
  amount or currency, bypass consent, or override a stopping rule.
- Deterministic policy defines the allowed action set and validates the final action.
- Human approval may authorize a reviewable action, but may not override a hard stop.
- Browser callbacks are presentation signals only.

## Authoritative live-run lifecycle

1. `awaiting_original_payment`
2. `original_payment_succeeded`, or `failure_stabilizing`
3. `diagnosing`
4. `awaiting_policy`
5. `awaiting_human_review`, or `executing_action`
6. `awaiting_recovery_payment`
7. `recovered`, `stopping_recovery`, `stopped`, `escalated`, `failed`, or `expired`

Every live-run response must expose the business state, active evidence step, waiting
reason, whether automation is complete, whether the financial outcome is terminal, and
provider-derived timestamps. A linked payment attempt is not proof of failure: only a
failed payment projection may open the failure path.

## Required backend capabilities

- Signed, duplicate-safe and out-of-order-safe webhook ingestion.
- Five-second signed-failure stabilization before recovery planning.
- Event-driven Payment Link paid, partially-paid, cancelled and expired outcomes, with
  polling only as fallback.
- Dynamic payment-rail incident context at planning and immediately before execution.
- Bounded AI evidence tools: payment snapshot, retry history, rail health and merchant
  policy.
- Human approval with reviewer, reason, expiry, optimistic version and policy
  revalidation.
- Idempotent provider actions and late-authorization compensation.
- Worker leases, bounded retries, heartbeats, queue lag and dead-letter visibility.
- Semantic audit events with model, prompt, policy and evidence versions.
- Reproducible batch evaluation with provider-backed and synthetic results kept separate.

## Backend release gates

- An original successful payment creates no recovery case.
- One signed failure creates exactly one case after stabilization.
- Gemini returns or deterministically falls back before its deadline.
- A current incident changes the recovery decision.
- Reviewable cases cannot execute before approval and revalidation.
- A provider action executes exactly once.
- A paid Payment Link becomes a measured outcome within five seconds.
- Unchanged reconciliation creates no duplicate evidence.
- Late authorization stops or compensates active recovery.
- A stale worker claim can be reclaimed safely.
- The audit chain verifies and the batch benchmark is reproducible.
