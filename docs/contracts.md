# ReclaimRail Integration and Agent Contracts

## 1. Purpose

This document defines the versioned interfaces between:

- Razorpay and the Webhook Gateway
- The Webhook Gateway and internal workers
- The Recovery Agent and diagnostic tools
- Gemini and the deterministic Policy Gate
- The Policy Gate and Action Executor
- The backend and operations dashboard

Every external or AI-generated value is untrusted until it passes the relevant contract and validation boundary.

## 2. Contract Versioning

Every internal message and structured AI response contains a `schema_version`.

Initial version:

```text
1.0
```

Rules:

1. Additive optional fields may remain within the same major version.
2. Renaming or removing a field requires a new major version.
3. Workers must reject unsupported major versions.
4. Raw events are preserved so they can be replayed through newer normalisers.
5. Agent prompt, model and schema versions are stored with every run.

## 3. Razorpay Webhook Contract

### Endpoint

```http
POST /webhooks/razorpay
Content-Type: application/json
X-Razorpay-Signature: <signature>
X-Razorpay-Event-Id: <unique-event-id>
```

### Required headers

| Header | Purpose |
|---|---|
| `Content-Type` | Must be `application/json` |
| `X-Razorpay-Signature` | HMAC-SHA256 signature used to authenticate the raw body |
| `X-Razorpay-Event-Id` | Unique event identifier used for idempotency |

Header lookup is case-insensitive.

### Signature verification

The signature is calculated over the exact raw request bytes:

```text
expected_signature =
    HMAC_SHA256(
        key = RAZORPAY_WEBHOOK_SECRET,
        message = raw_request_body
    )
```

Verification requirements:

1. Read the raw request body before JSON parsing.
2. Never re-serialise JSON for signature verification.
3. Use constant-time signature comparison.
4. The webhook secret is separate from the Razorpay API Key Secret.
5. An invalid signature must not create or update payment state.
6. Secrets and signature values must not be written to logs.

### Supported initial events

- `payment.failed`
- `payment.authorized`
- `payment.captured`

Additional event types may be stored but remain unsupported until a normaliser and tests are added.

### Example external envelope

All identifiers below are synthetic.

```json
{
  "entity": "event",
  "account_id": "acc_test_merchant",
  "event": "payment.failed",
  "contains": ["payment"],
  "payload": {
    "payment": {
      "entity": {
        "id": "pay_test_001",
        "entity": "payment",
        "amount": 49900,
        "currency": "INR",
        "status": "failed",
        "order_id": "order_test_001",
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment processing failed",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "error_reason": "payment_failed",
        "created_at": 1787500000
      }
    }
  },
  "created_at": 1787500001
}
```

The example describes shape only. Implementation must tolerate additional Razorpay fields.

## 4. Webhook Response Contract

### Accepted event

```http
200 OK
```

```json
{
  "status": "accepted",
  "event_id": "evt_internal_uuid",
  "correlation_id": "corr_uuid"
}
```

### Duplicate event

```http
200 OK
```

```json
{
  "status": "duplicate",
  "event_id": "evt_internal_uuid",
  "correlation_id": "corr_uuid"
}
```

### Invalid signature

```http
401 Unauthorized
```

```json
{
  "error": {
    "code": "WEBHOOK_SIGNATURE_INVALID",
    "message": "Webhook authentication failed.",
    "correlation_id": "corr_uuid"
  }
}
```

### Invalid payload

```http
422 Unprocessable Entity
```

```json
{
  "error": {
    "code": "WEBHOOK_PAYLOAD_INVALID",
    "message": "Webhook payload failed schema validation.",
    "correlation_id": "corr_uuid"
  }
}
```

### Durable storage unavailable

```http
503 Service Unavailable
```

```json
{
  "error": {
    "code": "WEBHOOK_STORAGE_UNAVAILABLE",
    "message": "The event could not be stored durably.",
    "correlation_id": "corr_uuid"
  }
}
```

A success response is returned only after the event is stored durably. Slow processing occurs asynchronously.

## 5. Webhook Idempotency Contract

Primary deduplication key:

```text
merchant_id + X-Razorpay-Event-Id
```

Fallback when the event header is absent:

```text
merchant_id + SHA256(raw_request_body)
```

Processing rules:

1. Insert the event using a unique database constraint.
2. If the constraint conflicts, fetch the existing event.
3. Return `200 duplicate`.
4. Do not enqueue another logical processing job.
5. Worker retries remain safe because state transitions and actions are separately idempotent.

## 6. Canonical Payment Event

The normaliser converts supported Razorpay events into this internal contract:

```json
{
  "schema_version": "1.0",
  "event_id": "evt_internal_uuid",
  "source_event_id": "razorpay_event_identifier",
  "correlation_id": "corr_uuid",
  "merchant_id": "merchant_uuid",
  "event_type": "PAYMENT_FAILED",
  "payment": {
    "razorpay_payment_id": "pay_test_001",
    "razorpay_order_id": "order_test_001",
    "amount_paise": 49900,
    "currency": "INR",
    "status": "FAILED",
    "method": "UPI",
    "provider": "SYNTHETIC_BANK",
    "error_code": "BAD_REQUEST_ERROR",
    "error_category": "PROVIDER_UNAVAILABLE"
  },
  "provider_created_at": "2026-08-23T15:46:40Z",
  "received_at": "2026-08-23T15:46:41Z",
  "payload_hash": "sha256_hex",
  "raw_event_record_id": "raw_event_uuid"
}
```

### CanonicalEventType

- `PAYMENT_FAILED`
- `PAYMENT_AUTHORIZED`
- `PAYMENT_CAPTURED`

### Normalisation rules

1. Amount remains in integer paise.
2. Currency is uppercase.
3. Method and provider values are normalised.
4. Unknown provider errors map to `UNKNOWN`.
5. Raw error fields remain available only in the stored raw event.
6. Internal services consume canonical events, not raw Razorpay payloads.
7. Unsupported events are stored and marked `UNSUPPORTED`; they are not silently discarded.

## 7. Background Job Contract

```json
{
  "schema_version": "1.0",
  "job_id": "job_uuid",
  "job_type": "PROCESS_PAYMENT_EVENT",
  "event_id": "evt_internal_uuid",
  "correlation_id": "corr_uuid",
  "attempt": 1,
  "created_at": "2026-08-23T15:46:41Z"
}
```

### JobType

- `PROCESS_PAYMENT_EVENT`
- `EVALUATE_INCIDENT_WINDOW`
- `RUN_RECOVERY_AGENT`
- `EXECUTE_RECOVERY_ACTION`
- `RECONCILE_RECOVERY_OUTCOME`

Requirements:

- `job_id` is unique.
- Consumers may receive a job more than once.
- Jobs must be idempotent.
- A job exceeding its retry limit moves to the dead-letter queue.
- Secrets and complete raw webhook bodies are not placed in Redis.

## 8. Diagnostic Tool Contract

The agent can call only four read-only tools:

- `get_payment_snapshot`
- `get_retry_history`
- `get_incident_health`
- `get_merchant_policy`

Every tool is scoped using `recovery_case_id`. Gemini cannot supply arbitrary merchant or payment identifiers.

### Common tool request

```json
{
  "schema_version": "1.0",
  "recovery_case_id": "case_uuid"
}
```

### Common tool result

```json
{
  "schema_version": "1.0",
  "tool_name": "get_payment_snapshot",
  "status": "SUCCEEDED",
  "evidence_id": "evidence_uuid",
  "observed_at": "2026-08-23T15:47:00Z",
  "data": {},
  "error": null
}
```

### Tool failure

```json
{
  "schema_version": "1.0",
  "tool_name": "get_payment_snapshot",
  "status": "FAILED",
  "evidence_id": null,
  "observed_at": "2026-08-23T15:47:00Z",
  "data": null,
  "error": {
    "code": "TOOL_DATA_UNAVAILABLE",
    "message": "Verified payment data is temporarily unavailable."
  }
}
```

Tool failures expose safe error categories, not database details or stack traces.

## 9. `get_payment_snapshot`

### Output data

```json
{
  "payment_id": "payment_uuid",
  "status": "FAILED",
  "amount_paise": 49900,
  "currency": "INR",
  "method": "UPI",
  "provider": "SYNTHETIC_BANK",
  "error_category": "PROVIDER_UNAVAILABLE",
  "status_age_seconds": 45,
  "authorized_at": null,
  "captured_at": null,
  "has_active_recovery_link": false,
  "payment_version": 3
}
```

This tool never returns customer payment credentials or API secrets.

## 10. `get_retry_history`

### Output data

```json
{
  "completed_attempts": 1,
  "maximum_attempts": 3,
  "last_attempt_at": "2026-08-23T15:40:00Z",
  "quiet_period_ends_at": "2026-08-23T15:55:00Z",
  "attempts": [
    {
      "attempt_number": 1,
      "attempt_type": "ORIGINAL",
      "status": "FAILED",
      "method": "UPI",
      "error_category": "PROVIDER_UNAVAILABLE"
    }
  ]
}
```

## 11. `get_incident_health`

### Output data

```json
{
  "matching_incident_id": "incident_uuid",
  "status": "OPEN",
  "severity": "HIGH",
  "payment_method": "UPI",
  "provider": "SYNTHETIC_BANK",
  "baseline_failure_rate": 0.08,
  "observed_failure_rate": 0.61,
  "robust_deviation_score": 5.4,
  "sample_count": 120,
  "detected_at": "2026-08-23T15:42:00Z"
}
```

If no matching incident exists:

```json
{
  "matching_incident_id": null,
  "status": "NONE"
}
```

## 12. `get_merchant_policy`

### Output data

```json
{
  "policy_id": "policy_uuid",
  "policy_version": 2,
  "max_retries": 3,
  "quiet_period_minutes": 15,
  "incident_circuit_breaker_enabled": true,
  "human_review_below_confidence": 0.72,
  "max_recovery_amount_paise": 100000,
  "allowed_actions": [
    "VERIFY_STATUS",
    "WAIT_FOR_INCIDENT_RECOVERY",
    "RETRY_LATER",
    "CREATE_PAYMENT_LINK",
    "SUGGEST_ALTERNATE_METHOD",
    "ESCALATE",
    "STOP"
  ]
}
```

## 13. Agent Execution Limits

Each agent run enforces:

| Limit | Value |
|---|---:|
| Maximum diagnostic tool calls | 4 |
| Maximum repeated call to the same tool | 1 |
| Maximum wall-clock duration | 20 seconds |
| Maximum plan explanation length | 300 characters |
| Required evidence references | At least 1 |
| Proposed actions | Exactly 1 |

A timeout, invalid response or exhausted tool budget triggers deterministic fallback and human review.

## 14. Gemini Recovery Plan Contract

Gemini must return JSON matching this logical schema:

```json
{
  "schema_version": "1.0",
  "root_cause_category": "BANK_OR_PROVIDER",
  "recoverability": "HIGH",
  "urgency": "MEDIUM",
  "confidence": 0.91,
  "evidence_ids": [
    "evidence_payment_uuid",
    "evidence_incident_uuid"
  ],
  "proposed_action": "WAIT_FOR_INCIDENT_RECOVERY",
  "explanation": "A matching provider incident is active, so another immediate retry would likely repeat the failure.",
  "requires_human_review": false
}
```

### Field constraints

| Field | Constraint |
|---|---|
| `schema_version` | Must equal `1.0` |
| `root_cause_category` | Controlled enum |
| `recoverability` | `LOW`, `MEDIUM`, `HIGH`, `UNKNOWN` |
| `urgency` | `LOW`, `MEDIUM`, `HIGH` |
| `confidence` | Number from `0.0` to `1.0` |
| `evidence_ids` | Between 1 and 8 valid evidence identifiers |
| `proposed_action` | Exactly one allowed action |
| `explanation` | Non-empty and at most 300 characters |
| `requires_human_review` | Boolean |
| Additional fields | Rejected |

### RootCauseCategory

- `CUSTOMER`
- `AUTHENTICATION`
- `BANK_OR_PROVIDER`
- `NETWORK`
- `MERCHANT_INTEGRATION`
- `RISK`
- `UNKNOWN`

### AI validation rules

1. Parse through a Pydantic model.
2. Reject additional fields.
3. Reject nonexistent evidence identifiers.
4. Reject action values outside the allow-list.
5. Reject confidence outside `0.0–1.0`.
6. Force review when root cause is `UNKNOWN`.
7. Force review when confidence is below merchant policy.
8. Store the original model response in a redacted agent trace.
9. Never execute a plan directly.

## 15. Deterministic Fallback Plan

Used when Gemini is unavailable, times out or fails schema validation:

```json
{
  "schema_version": "1.0",
  "root_cause_category": "UNKNOWN",
  "recoverability": "UNKNOWN",
  "urgency": "MEDIUM",
  "confidence": 0.0,
  "evidence_ids": ["fallback_reason_uuid"],
  "proposed_action": "ESCALATE",
  "explanation": "Automated planning was unavailable; manual review is required.",
  "requires_human_review": true
}
```

## 16. Policy Gate Input

```json
{
  "schema_version": "1.0",
  "evaluation_id": "evaluation_uuid",
  "evaluated_at": "2026-08-23T15:47:02Z",
  "recovery_case": {
    "id": "case_uuid",
    "status": "PLANNED",
    "retry_count": 1,
    "at_risk_amount_paise": 49900
  },
  "payment": {
    "id": "payment_uuid",
    "status": "FAILED",
    "amount_paise": 49900,
    "currency": "INR",
    "version": 3,
    "has_active_recovery_link": false
  },
  "incident": {
    "id": "incident_uuid",
    "status": "OPEN",
    "severity": "HIGH"
  },
  "merchant_policy": {
    "id": "policy_uuid",
    "version": 2,
    "max_retries": 3,
    "quiet_period_minutes": 15,
    "incident_circuit_breaker_enabled": true,
    "human_review_below_confidence": 0.72,
    "max_recovery_amount_paise": 100000,
    "allowed_actions": [
      "VERIFY_STATUS",
      "WAIT_FOR_INCIDENT_RECOVERY",
      "RETRY_LATER",
      "CREATE_PAYMENT_LINK",
      "SUGGEST_ALTERNATE_METHOD",
      "ESCALATE",
      "STOP"
    ]
  },
  "recovery_plan": {
    "id": "plan_uuid",
    "confidence": 0.91,
    "proposed_action": "WAIT_FOR_INCIDENT_RECOVERY",
    "requires_human_review": false,
    "evidence_ids": [
      "evidence_payment_uuid",
      "evidence_incident_uuid"
    ]
  }
}
```

## 17. Stable Policy Rule Identifiers

- `PAYMENT_STATUS_ELIGIBLE`
- `PAYMENT_AMOUNT_CURRENCY_MATCH`
- `PAYMENT_STATUS_FRESH`
- `ACTION_ALLOWED_FOR_MERCHANT`
- `RETRY_BUDGET_AVAILABLE`
- `QUIET_PERIOD_ELAPSED`
- `INCIDENT_CIRCUIT_BREAKER_CLEAR`
- `NO_ACTIVE_PAYMENT_LINK`
- `CONFIDENCE_THRESHOLD_MET`
- `HIGH_VALUE_REVIEW_COMPLETE`
- `EVIDENCE_REFERENCES_VALID`
- `RECOVERY_CASE_ACTIVE`

Stable identifiers make policy outcomes testable and auditable.

## 18. Policy Gate Output

### Permitted action

```json
{
  "schema_version": "1.0",
  "policy_decision_id": "decision_uuid",
  "decision": "PERMITTED",
  "approved_action": "VERIFY_STATUS",
  "reason_codes": [],
  "rule_results": [
    {
      "rule_id": "PAYMENT_STATUS_ELIGIBLE",
      "passed": true
    }
  ],
  "safe_parameters": {},
  "expected_payment_version": 3,
  "revalidate_before_execution": true,
  "evaluated_at": "2026-08-23T15:47:02Z"
}
```

### Deferred action

```json
{
  "schema_version": "1.0",
  "policy_decision_id": "decision_uuid",
  "decision": "DEFERRED",
  "approved_action": "WAIT_FOR_INCIDENT_RECOVERY",
  "reason_codes": ["ACTIVE_PROVIDER_INCIDENT"],
  "rule_results": [
    {
      "rule_id": "INCIDENT_CIRCUIT_BREAKER_CLEAR",
      "passed": false
    }
  ],
  "safe_parameters": {
    "recheck_after_seconds": 900
  },
  "expected_payment_version": 3,
  "revalidate_before_execution": true,
  "evaluated_at": "2026-08-23T15:47:02Z"
}
```

### Blocked action

```json
{
  "schema_version": "1.0",
  "policy_decision_id": "decision_uuid",
  "decision": "BLOCKED",
  "approved_action": "STOP",
  "reason_codes": ["PAYMENT_ALREADY_AUTHORIZED"],
  "rule_results": [
    {
      "rule_id": "PAYMENT_STATUS_ELIGIBLE",
      "passed": false
    }
  ],
  "safe_parameters": {},
  "expected_payment_version": 4,
  "revalidate_before_execution": true,
  "evaluated_at": "2026-08-23T15:47:02Z"
}
```

Only deterministic code constructs `safe_parameters`.

## 19. Action Execution Command

```json
{
  "schema_version": "1.0",
  "action_id": "action_uuid",
  "recovery_case_id": "case_uuid",
  "policy_decision_id": "decision_uuid",
  "action_type": "CREATE_PAYMENT_LINK",
  "idempotency_key": "reclaimrail:case_uuid:decision_uuid",
  "expected_payment_version": 3,
  "safe_parameters": {
    "amount_paise": 49900,
    "currency": "INR",
    "expire_by": "2026-08-24T15:47:02Z"
  },
  "correlation_id": "corr_uuid",
  "created_at": "2026-08-23T15:47:02Z"
}
```

Execution requirements:

1. Reload the payment from PostgreSQL.
2. Fetch current Razorpay status when an external action is possible.
3. Compare the current payment version with `expected_payment_version`.
4. Re-run safety-critical policy checks.
5. Acquire an action-specific idempotency lock.
6. Execute at most once.
7. Persist the result before acknowledging job completion.
8. Never log credentials or complete payment-link URLs.

## 20. Action Result Contract

```json
{
  "schema_version": "1.0",
  "action_id": "action_uuid",
  "status": "SUCCEEDED",
  "external_reference": "plink_test_reference",
  "failure_code": null,
  "safe_message": "A Test Mode recovery payment link was created.",
  "observed_at": "2026-08-23T15:47:04Z",
  "correlation_id": "corr_uuid"
}
```

### ActionResultStatus

- `SUCCEEDED`
- `FAILED`
- `SKIPPED`
- `CANCELLED`

`SKIPPED` is used when revalidation shows that the action is no longer necessary or safe.

## 21. Human Review Contract

### Endpoint

```http
POST /api/v1/recovery-cases/{recovery_case_id}/review
```

### Request

```json
{
  "decision": "APPROVE",
  "comment": "Verified that the merchant permits an alternate method.",
  "expected_case_version": 5
}
```

### Decision enum

- `APPROVE`
- `REJECT`

Approval requirements:

- Authenticate the reviewer.
- Validate the expected case version.
- Store the reviewer identity.
- Re-run payment-status and policy checks.
- Never treat human approval as permission to bypass safety invariants.

## 22. Dashboard API Surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Database and Redis readiness |
| `GET` | `/api/v1/incidents` | List incidents |
| `GET` | `/api/v1/incidents/{id}` | Incident timeline and affected payments |
| `GET` | `/api/v1/recovery-cases` | Prioritised recovery queue |
| `GET` | `/api/v1/recovery-cases/{id}` | Full recovery and agent trace |
| `POST` | `/api/v1/recovery-cases/{id}/review` | Approve or reject review |
| `GET` | `/api/v1/metrics/recovery` | Recovery and safety metrics |
| `POST` | `/api/v1/replay-runs` | Execute a seeded Replay Lab batch |
| `GET` | `/api/v1/replay-runs/{id}` | Fetch replay comparison |
| `POST` | `/api/v1/simulations/policy` | Simulate a plan against policy |
| `POST` | `/api/v1/failure-injections` | Trigger a controlled demo failure |

Mutating demonstration endpoints are disabled outside Test/Demo environments.

## 23. Standard API Error Envelope

```json
{
  "error": {
    "code": "RECOVERY_CASE_VERSION_CONFLICT",
    "message": "The recovery case changed. Refresh and try again.",
    "correlation_id": "corr_uuid",
    "details": []
  }
}
```

Rules:

- Error codes are stable and machine-readable.
- Messages are safe for display.
- Stack traces and secrets never appear in API responses.
- Validation details identify fields without exposing internal infrastructure.

## 24. Audit Event Contract

```json
{
  "schema_version": "1.0",
  "audit_id": "audit_uuid",
  "recovery_case_id": "case_uuid",
  "actor_type": "POLICY",
  "actor_reference": "policy-engine:v1",
  "event_type": "RECOVERY_ACTION_BLOCKED",
  "entity_type": "POLICY_DECISION",
  "entity_id": "decision_uuid",
  "summary": "Recovery action was blocked because the payment was already authorized.",
  "details": {
    "reason_codes": ["PAYMENT_ALREADY_AUTHORIZED"]
  },
  "correlation_id": "corr_uuid",
  "occurred_at": "2026-08-23T15:47:02Z"
}
```

Audit records are append-only and contain redacted details.

## 25. Required Contract Tests

### Webhook tests

1. Valid raw body and valid signature are accepted.
2. Modified body with the original signature is rejected.
3. Duplicate `X-Razorpay-Event-Id` is accepted without duplicate processing.
4. Missing event ID uses the payload-hash fallback.
5. Supported events normalise correctly.
6. Unsupported events are preserved without changing payment state.
7. Out-of-order authorization and capture events do not regress state.

### Tool tests

1. Every tool is read-only.
2. Tool access is scoped to the supplied recovery case.
3. A fifth tool call is rejected.
4. Repeating the same tool is rejected.
5. Tool failures return safe error codes.
6. Tool results contain no secrets or unnecessary PII.

### Gemini-plan tests

1. Every allowed action parses successfully.
2. Unknown actions fail validation.
3. Additional properties fail validation.
4. Missing evidence fails validation.
5. Invalid confidence fails validation.
6. Unknown root cause forces review.
7. Timeout produces the deterministic fallback.

### Policy tests

1. Authorized payment blocks recovery.
2. Active incident defers matching retries.
3. Retry limit blocks another attempt.
4. Quiet period defers another attempt.
5. Existing active link blocks duplicate-link creation.
6. Low confidence requires review.
7. High amount requires review.
8. Disallowed merchant action is blocked.
9. Stale payment version skips execution.
10. A repeated action command executes at most once.

## 26. References

- [Razorpay — Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/)
- [Razorpay — Payments Webhook Events](https://razorpay.com/docs/webhooks/payments/)
- [Razorpay — Set Up Payment Webhooks](https://razorpay.com/docs/webhooks/setup-edit-payments/)
- [Gemini API — Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API — Function Calling](https://ai.google.dev/gemini-api/docs/function-calling)