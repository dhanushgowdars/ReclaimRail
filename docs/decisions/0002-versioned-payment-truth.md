# ADR-0002: Use Versioned Payment Truth Built from Evidence

- **Status:** Accepted
- **Date:** 2026-09-22

## Context

A client timeout, missing webhook or internal failure does not prove that a payment
failed. Provider, webhook and merchant records can temporarily disagree.

## Decision

ReclaimRail will store immutable evidence records and resolve a versioned payment
truth snapshot. `OUTCOME_UNKNOWN` and `SOURCE_CONFLICT` are first-class states.
Every plan, policy decision and approval will identify the truth version it used.

## Consequences

- Recovery pauses or escalates when money movement cannot be established safely.
- New evidence can invalidate an existing plan or approval.
- Reviewers can reproduce why a truth decision was made.
