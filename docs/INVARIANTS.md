# ReclaimRail Safety Invariants

These rules are architectural constraints, not prompt suggestions. Runtime,
workers, provider adapters, AI planners and operator interfaces must preserve
them. A phase cannot be marked complete while its tests violate an invariant.

## Payment truth

1. `OUTCOME_UNKNOWN` is never treated as payment failure.
2. A recovery action uses a versioned truth snapshot built from stored evidence.
3. Evidence preserves source identity, event time, observation time, verification
   state, freshness and a content hash.
4. Conflicting sources produce `SOURCE_CONFLICT` or escalation; source order alone
   cannot silently resolve the conflict.
5. New material evidence creates a new truth version and makes older plans stale.

## AI authority

6. The AI may investigate evidence and propose a typed recovery intent; it cannot
   authorize or execute a money-changing action.
7. Every factual AI claim cites one or more stored evidence identifiers.
8. The model cannot choose the amount, customer coordinates, provider resource ID,
   provider URL, retry limit, policy threshold or approval result.
9. Unsupported claims, invalid evidence identifiers, malformed output and model
   unavailability fail closed to deterministic fallback, abstention or escalation.
10. Untrusted provider, merchant and customer text is data, never instruction.

## Policy and approval

11. Deterministic policy evaluates the latest case and truth versions.
12. Approval binds case version, truth version, action, backend-resolved amount,
    evidence digest, approver and expiry.
13. New material evidence invalidates an older approval before execution.
14. A human approval cannot override completed payment, duplicate-payment, stale
    evidence, ownership or hard amount safety rules.

## Provider execution

15. No provider-changing call occurs before a durable action intent is committed.
16. Every provider-changing action has a deterministic idempotency key and
    concurrency protection.
17. A lost or ambiguous provider response becomes `IN_FLIGHT` or
    `RECONCILIATION_REQUIRED`; it is not treated as failure and blindly retried.
18. Reconciliation happens before retry.
19. Provider action success is verified against provider state before it can become
    an attributed recovery outcome.
20. Amounts are positive integer minor units; currency and case ownership are
    validated by trusted backend data.

## Evidence and evaluation

21. Recovery receipts bind truth, evidence, decision, approval, execution and
    outcome using tamper-evident hashes.
22. Action success, payment success and attributed recovery are separate metrics.
23. Synthetic, simulated and Test Mode results remain clearly labelled and cannot
    be presented as production revenue.
24. Missing denominators produce unavailable metrics, not invented zeroes or
    percentages.
25. Deterministic fallback is visible and is never reported as a Gemini decision.
