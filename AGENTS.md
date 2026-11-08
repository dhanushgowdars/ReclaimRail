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

Never convert `PARTIAL`, `BROKEN` or `NOT IMPLEMENTED` to `VERIFIED` from file presence,
a mocked happy path, a screenshot, an old CI run or an earlier chat statement.

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
7. All judge-relevant backend behavior must have a truthful, understandable frontend
   representation using persisted backend evidence.
8. Append the commands and results to `docs/product/WORK-LOG.md`.
9. Update the acceptance matrix and current-state document in the same phase.
10. Stop for owner review before beginning another phase.

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

## Safety and repository hygiene

- Preserve uncommitted and untracked work until it is inventoried and the owner chooses
  whether to keep, split or discard it.
- Never commit `.env`, provider credentials, customer data, database files or raw private
  provider payloads.
- Use integer minor units plus explicit currency for money.
- Keep Test Mode, replay, controlled synthetic and production evidence visibly separate.
- A created Payment Link is not recovered revenue. Only verified provider evidence may
  change the Outcome Ledger to recovered.
- Provider ambiguity requires reconciliation before retry.
- Use Windows PowerShell for commands intended for the owner.
- Do not modify application code during an audit-only phase.
