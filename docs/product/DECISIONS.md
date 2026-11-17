# ReclaimRail decisions

This is an append-only decision register. Do not silently change a locked decision. A
replacement must identify the prior decision, owner, date, reason and migration impact.

## Locked decisions

| ID | Date | Decision | Reason |
| --- | --- | --- | --- |
| DEC-001 | 2026-10-31 | Repository evidence overrides earlier chat claims. | The reset exists because plans and completion claims drifted across chats. |
| DEC-002 | 2026-10-31 | Use only `VERIFIED`, `PARTIAL`, `BROKEN`, `OBSOLETE` and `NOT IMPLEMENTED` for audited product state. | Prevent ambiguous terms such as “basically complete.” |
| DEC-003 | 2026-10-31 | Gemini is advisory. Deterministic truth, policy, approval and provider reconciliation remain authoritative. | A model response cannot safely establish or move money. |
| DEC-004 | 2026-10-31 | Preserve the current Phase 17B worktree until it is inventoried and the owner approves a keep/split/discard action. | It contains staged, unstaged and untracked work that cannot be reconstructed from `main`. |
| DEC-005 | 2026-10-31 | Do not repeatedly run live Gemini benchmarks. | Focused deterministic tests should diagnose contracts first; quota/provider noise is expensive and inconclusive. |
| DEC-006 | 2026-10-31 | Every judge-relevant backend behavior requires truthful frontend evidence. | Hidden backend work does not complete the judge experience. |
| DEC-007 | 2026-10-31 | Test Mode, replay, controlled synthetic and production evidence remain separate. | Synthetic money cannot be presented as recovered merchant revenue. |
| DEC-008 | 2026-10-31 | A Payment Link is pending value until verified provider evidence confirms payment and attribution. | Provider action success is not financial success. |
| DEC-009 | 2026-10-31 | Future commits use only `Dhanush R S <dhanushrs981@gmail.com>`. | Required owner identity; no AI attribution in Git metadata. |
| DEC-010 | 2026-10-31 | Do not rewrite history or delete local/remote branches during the audit. | History cleanup is destructive and requires an explicit, separate owner decision. |
| DEC-011 | 2026-10-31 | Implement exactly one approved phase at a time. | Keeps acceptance evidence attributable and prevents another moving-plan loop. |
| DEC-012 | 2026-10-31 | Do not remove or simplify promised features without an owner-approved replacement/defer decision. | Scope changes must be visible and deliberate. |
| DEC-013 | 2026-10-31 | Freeze the original mixed Phase 17B worktree and continue from a separate `audit/current-state-reset` worktree based on `19126456...`; port no application WIP until its approved phase. | Preserves every staged/unstaged/untracked state while establishing a clean, evidence-led continuation without silently adopting broken Phase 17B behavior. |
| DEC-014 | 2026-11-08 | Gate 1 authorizes baseline reproduction only: ignored local environment preparation, locked dependency installation, isolated infrastructure, migrations, tests, startup and bounded acceptance evidence; it does not authorize application behavior changes. | Separates diagnosis from implementation and prevents an observed failure from being silently patched during its audit. |
| DEC-015 | 2026-11-08 | A locally signed controlled synthetic webhook is not provider-emitted Razorpay Test Mode evidence. Both may exercise the same intake contract, but their provenance and provider-verification consequences must remain explicit. | The Gate 1 payload used synthetic order/payment identifiers and triggered live provider-read failures; calling it provider Test Mode evidence would be misleading. |
| DEC-016 | 2026-11-08 | Stop the runtime and classify Gate 1 as `BROKEN` when provider calls, evidence rows and truth versions amplify without new information. Do not force recovery eligibility or insert a case to bypass deterministic truth. | The worker logged 453 unavailable reconciliation batches and the case service correctly refused `recovery_not_eligible`; bypassing that result would defeat the audit and safety model. |

## Existing architectural decisions retained

The following ADRs remain authoritative unless explicitly replaced:

- `docs/decisions/0001-bounded-recovery-agent.md`
- `docs/decisions/0002-versioned-payment-truth.md`
- `docs/decisions/0003-ai-authority-boundary.md`
- `docs/decisions/0004-durable-provider-execution.md`
- `docs/decisions/0005-honest-recovery-evaluation.md`

## Owner decisions required before implementation

| ID | Decision required | Options and consequence | Recommended default |
| --- | --- | --- | --- |
| OPEN-001 | RESOLVED by `DEC-013`: mixed Phase 17B preservation and clean continuation. | Complete local backup plus frozen original worktree; clean audit worktree contains documentation only. | No further cleanup or WIP port occurs without phase approval. |
| OPEN-002 | Should old remote branches with AI/wrong-email authors be deleted later? | Keep for history; or delete merged remote branches after verifying `main` contains all required work. History rewrite is not recommended. | Defer until the product branch is stable; clean branches without rewriting `main`. |
| OPEN-003 | What is the public-demo access model? | Controlled shared reviewer code; authenticated single-merchant demo; or production-style users/tenants. | Controlled demo for submission, with all read endpoints protected before public deployment. |
| OPEN-004 | Which deployment target is required? | Local-only judge demo, temporary public demo, or production-style hosted stack. | Decide before Phase 21 because security and operations gates depend on it. |
| OPEN-005 | What live Gemini budget is allowed for Phase 17B? | Models, maximum requests, maximum spend and retry policy. | One frozen-corpus run after deterministic diagnostics; no automatic repeated retries across the corpus. |
| OPEN-006 | How should obsolete tracked backups and ignored runtime reports be retained? | Delete, archive outside Git, or keep selected acceptance reports only. | Keep a small sanitized acceptance bundle; remove code backups after explicit approval. |
| OPEN-007 | Is the existing 24-hour approval TTL still required for every protected action? | Retain, shorten for demo, or make policy-specific. | Retain the 24-hour product rule; allow only a separately labelled accelerated Test Mode scenario if needed. |
| OPEN-008 | What evaluation claim should the submission make? | Safety/policy evidence only; simulated comparative recovery; or a statistically designed Test Mode cohort. | Build an honest paired synthetic/Test Mode evaluation with baseline and confidence intervals; never claim production revenue. |
| OPEN-009 | Authorize a dedicated Gate 1A remediation for `G1-P0-001` before Gate 2? | Approve the bounded reconciliation/evidence-idempotency fix and its tests; defer and leave the full stack unsafe to restart with live provider reads; or revise the acceptance contract explicitly. | Approve Gate 1A only after reviewing the documented defect and proposed file/test scope. No application edit is authorized by this register entry. |
