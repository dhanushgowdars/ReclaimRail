from app.services.recovery_ai_trace import build_recovery_ai_trace


def test_projects_only_safe_bounded_planner_evidence() -> None:
    trace = build_recovery_ai_trace(
        {
            "planner": {
                "fallback_used": False,
                "input_token_count": 111,
                "output_token_count": 22,
            },
            "bounded_ai_analysis": {
                "root_cause_category": "bank_authorization_failure",
                "recoverability_assessment": "recoverable",
                "confidence": 0.82,
                "allowed_action_recommendation": "create_payment_link",
                "evidence_references": ["payment_state_snapshot"],
            },
            "evidence_codes": ["payment_failed"],
            "bounded_ai_evidence_tools": {
                "payment_state_snapshot": {"state": "failed"},
                "merchant_recovery_policy": {"customer_contact_allowed": True},
            },
            "raw_prompt": "must never appear in the response",
            "customer_email": "must never appear in the response",
        },
    )

    assert trace.confidence == 0.82
    assert trace.evidence_tool_names == (
        "merchant_recovery_policy",
        "payment_state_snapshot",
    )
    assert not hasattr(trace, "raw_prompt")
    assert not hasattr(trace, "customer_email")


def test_supports_legacy_flat_fallback_metadata() -> None:
    trace = build_recovery_ai_trace(
        {"fallback_used": True, "fallback_reason": "provider_failure"},
    )

    assert trace.fallback_used is True
    assert trace.fallback_reason == "provider_failure"
