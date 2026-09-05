from app.services.recovery_ai_trace import build_recovery_ai_trace, display_recovery_ai_text


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
                "reasoning_items": [
                    {
                        "evidence_references": ["payment_state_snapshot"],
                        "interpretation": "The payment is failed.",
                        "action_impact": "Recovery can be evaluated.",
                    },
                ],
                "alternatives_considered": [
                    {
                        "action_type": "wait",
                        "disposition": "not_selected",
                        "reason": "No active incident is cited.",
                        "evidence_references": ["payment_state_snapshot"],
                    },
                ],
                "known_uncertainties": ["Customer intent is not recorded."],
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

    assert trace.evidence_citations[0].label == "Recorded payment state"
    assert trace.evidence_citations[0].observations == ("State: failed",)
    assert trace.evidence_tool_names == (
        "merchant_recovery_policy",
        "payment_state_snapshot",
    )
    assert trace.reasoning_items[0].action_impact == "Recovery can be evaluated."
    assert trace.alternatives_considered[0].action_type == "wait"
    assert trace.known_uncertainties == ("Customer intent is not recorded.",)
    assert not hasattr(trace, "raw_prompt")
    assert not hasattr(trace, "customer_email")


def test_supports_legacy_flat_fallback_metadata() -> None:
    trace = build_recovery_ai_trace(
        {"fallback_used": True, "fallback_reason": "provider_failure"},
    )

    assert trace.fallback_used is True
    assert trace.fallback_reason == "provider_failure"


def test_formats_minor_units_for_operator_display() -> None:
    evidence = {
        "bounded_ai_analysis": {
            "evidence_references": ["payment_state_snapshot", "merchant_recovery_policy"],
            "operator_explanation": "Recover the 349900 INR payment within limit 5000000.",
        },
        "bounded_ai_evidence_tools": {
            "payment_state_snapshot": {
                "state": "failed",
                "amount_minor": 349900,
                "currency": "INR",
            },
            "merchant_recovery_policy": {"automatic_amount_limit_minor": 5000000},
        },
    }

    trace = build_recovery_ai_trace(evidence)
    assert trace.operator_explanation == "Recover the ₹3,499 INR payment within limit ₹50,000."
    assert trace.evidence_citations[0].observations == (
        "State: failed",
        "Amount: ₹3,499",
        "Currency: INR",
    )
    assert display_recovery_ai_text("Original amount 349900", evidence) == "Original amount ₹3,499"
