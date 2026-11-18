# ReclaimRail repository operating contract

This file governs every future change to this repository. Read it before planning,
editing, testing, committing or making a completion claim.

## Authority and identity

- Product owner: Dhanush R S.
- Required Git author and committer: `Dhanush R S <dhanushrs981@gmail.com>`.
- Never add Codex, ChatGPT, OpenAI or another AI as author, committer or co-author.
- Never rewrite history, delete branches, discard local work or remove promised scope
  without an explicit owner decision.
- The deterministic payment-truth resolver, deterministic policy engine, state-bound
  approval and provider reconciliation are authoritative. Gemini may investigate and
  propose; it may not establish financial truth, authorize or execute a money action.

## Evidence classifications

Use exactly these labels in status documents:

- `VERIFIED`: the current code path exists and its applicable automated/runtime gate
  has passed with recorded evidence.
- `PARTIAL`: useful implementation exists, but one or more mandatory acceptance gates
  are absent, stale or unverified.
- `BROKEN`: a current required gate reproducibly fails or the implementation contradicts
  its contract.
- `OBSOLETE`: retained material has been superseded or no longer describes the current
  product/runtime.
- `NOT IMPLEMENTED`: no acceptable runtime path exists for the requirement.
- `NEEDS INSPECTION`: current repository/runtime evidence is insufficient to classify the
  requirement safely. This is a temporary audit state, not a completion claim.

Never convert `PARTIAL`, `BROKEN` or `NOT IMPLEMENTED` to `VERIFIED` from file presence,
a mocked happy path, a screenshot, an old CI run or an earlier chat statement.

## Document authority and navigation

The six audit documents remain authoritative for current state and implementation control.
`docs/product/UNIFIED-MASTER-ROADMAP.md` is the owner-approved consolidated product
blueprint and complete feature catalogue. It was locked on 18 November 2026 and remains
subordinate to current repository evidence for status claims.

Read in this order:

1. `AGENTS.md`;
2. `docs/product/CURRENT-STATE.md`;
3. `docs/product/MASTER-EXECUTION-PLAN.md`;
4. active rows in `docs/product/ACCEPTANCE-MATRIX.md`;
5. `docs/product/DECISIONS.md`;
6. latest entries in `docs/product/WORK-LOG.md`; and
7. `docs/product/UNIFIED-MASTER-ROADMAP.md` for consolidated scope and priorities.

The unified roadmap's M0–M8 milestones do not renumber or reorder the established gates.
Gate 1A is closed by the owner-authorized 23-path local commit recorded in Git history.
Gate 2 is the only active work order. Its uncommitted candidate lives on
`gate2/dependency-access-control`. The owner accepted the bounded dev-only dependency risk,
and the exact candidate passed Windows/PostgreSQL, complete regression, controller and
reviewer-session validation on 18 November 2026. Its technical acceptance rows are
`VERIFIED`, but the work order remains `PARTIAL` until the owner reviews the reconciled
documentation diff and separately authorizes the exact local commit. Do not rerun Gate 1A
or Gate 2 evidence unless new repository evidence invalidates the recorded results, and do
not begin Phase 17B before the Gate 2 commit is authorized and verified.

## Required workflow

1. Start from a clean branch based on the approved baseline.
2. Read `docs/INVARIANTS.md`, `docs/product/CURRENT-STATE.md`,
   `docs/product/MASTER-EXECUTION-PLAN.md`, `docs/product/DECISIONS.md`, and the
   active rows in `docs/product/ACCEPTANCE-MATRIX.md`.
3. Implement one approved phase only. Do not mix cleanup, dependency upgrades and
   feature work unless the phase explicitly contains them.
4. Implement in this order: contract, persistence, deterministic domain behavior,
   adapters/services, workers/API, negative/race tests, frontend evidence, docs.
5. Run focused deterministic tests before any live-provider test.
6. Do not repeatedly run the Gemini frozen corpus. A live run requires a documented
   reason, fixed corpus, model list, request budget and output path.
7. Every provider-read loop requires a persisted retry budget, cooldown/backoff and a
   terminal or operator-visible state. A timestamp must not make identical failure
   evidence unique on every poll. Stop the runtime if provider calls, evidence rows or
   truth versions amplify without new external information.
8. Controlled synthetic provider identifiers must not be sent to a live provider adapter.
   Synthetic, replay and provider-emitted Test Mode evidence must remain separately
   labelled in commands, logs, persistence and completion claims.
9. All judge-relevant backend behavior must have a truthful, understandable frontend
   representation using persisted backend evidence.
10. Append the commands and results to `docs/product/WORK-LOG.md`.
11. Update the acceptance matrix and current-state document in the same phase.
12. Stop for owner review before beginning another phase.
13. Browser evidence must be inspected visually after capture. Record clipped navigation,
    horizontal-scroll-only columns, loading/animation washout and any state that is present
    in JSON or the DOM but not legible in the screenshot; do not promote it to clean visual
    proof from an automated assertion alone.

## Completion claim contract

Every phase completion claim must state:

- phase and requirement IDs;
- changed files;
- commands run;
- exact test/lint/build/migration/security results;
- frontend evidence and how it was obtained;
- live-provider evidence, or an explicit `not run`;
- remaining limitations, skipped tests and environmental blockers;
- branch, commit and author/committer identity.

A phase is not complete while a mandatory check is failing, skipped without an approved
reason, supported only by ignored local artifacts, or invisible in the frontend.
An uncommitted candidate may satisfy individual acceptance rows, but the phase remains
`PARTIAL` until its required end-to-end rerun, documentation and owner-reviewed commit gate
are complete.

## Safety and repository hygiene

- Preserve uncommitted and untracked work until it is inventoried and the owner chooses
  whether to keep, split or discard it.
- Never commit `.env`, provider credentials, customer data, database files or raw private
  provider payloads.
- Use integer minor units plus explicit currency for money.
- Keep Test Mode, replay, controlled synthetic and production evidence visibly separate.
- Do not claim that no provider call occurred merely because the initiating command did
  not call the provider; account for every enabled background worker before making that
  claim.
- A created Payment Link is not recovered revenue. Only verified provider evidence may
  change the Outcome Ledger to recovered.
- Provider ambiguity requires reconciliation before retry.
- Use Windows PowerShell for commands intended for the owner.
- Do not modify application code during an audit-only phase.
