# ADR-0001: Use a Bounded Recovery Agent

- **Status:** Accepted
- **Date:** 2026-08-23
- **Track:** Razorpay AI Revenue Recovery

## Context

ReclaimRail must detect revenue at risk, determine an appropriate intervention and execute a bounded recovery workflow.

Payment recovery contains two different kinds of decisions:

1. Deterministic safety decisions involving payment state, amount, currency, retry limits, idempotency and permissions.
2. Contextual judgement involving likely root cause, recoverability, urgency and the most appropriate intervention.

Using an LLM for both categories would make monetary actions unpredictable and difficult to audit. Using only fixed rules would make the system less capable of interpreting combined payment, incident and retry evidence.

## Decision

ReclaimRail will use Gemini as a bounded, tool-using Recovery Agent.

The agent follows:

```text
Observe → Investigate → Plan → Policy Gate → Act → Observe Outcome