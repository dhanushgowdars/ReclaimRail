# Phase 17 Acceptance Matrix

| ID | Implementation evidence | Automated proof | State before final merge |
| --- | --- | --- | --- |
| P17-01 | `recovery_investigation_tools.py`, registry v1, 11 read-only tools | registry and forbidden-tool tests | Implemented |
| P17-02 | case ID validation plus `observed_at/resolved_at <= evidence_cutoff_at` | cross-case/extra-input tests; SQL filters | Implemented |
| P17-03 | session/step tables and migration `e7a1c2d3f417` | model/API tests; PostgreSQL gate pending | Verify on PostgreSQL |
| P17-04 | durable hypothesis table with status, citations and version | strict hypothesis contract and service persistence path | Implemented |
| P17-05 | four independent budgets stored on the session | tool/token/retry fallback tests; wall-clock timeout boundary | Implemented |
| P17-06 | Pydantic `extra=forbid` turn/hypothesis contracts | malformed, extra-field and invalid terminal-shape tests | Implemented |
| P17-07 | objective, case reference, tool catalog and observations only | nested deterministic-baseline rejection test | Implemented |
| P17-08 | terminal `abstained` state and reason | explicit conflicting-evidence abstention test | Implemented |
| P17-09 | `fallback` state with terminal reason and provider label | unavailable, malformed, token and tool-budget paths | Implemented |
| P17-10 | `EvidenceInvestigatorProvider` protocol and Google adapter | scripted fake adapter paths; configured adapter code | Implemented |
| P17-11 | recursive sensitive-key redaction; capabilities expose no raw contact | nested email/phone redaction test | Implemented |
| P17-12 | model sees provider facts only through persisted `payment_evidence` | unknown/unreturned citation rejection | Implemented; DB gate pending |
| P17-13 | unique `(case, version)` plus IntegrityError reload | repeat invocation does not call provider | Implemented; race checked by DB constraint |
| P17-14 | truth update invalidates running old-version sessions | payment-truth invalidation statement test and runtime version recheck | Implemented |
| P17-15 | case-detail service/route/types/page expose safe trace | endpoint serialization and frontend build | Implemented |
| P17-16 | investigator registry contains no mutation tool; runtime is labelled shadow | three sequence tests persist steps only; existing recovery tests pass | Implemented |

## Exit decision

Do not mark Phase 17 complete or begin Phase 18 until PostgreSQL migration/schema checks, the full
backend suite, GitHub CI and owner-only authorship all pass on the applied branch.
