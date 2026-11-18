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
| DEC-017 | 2026-11-17 | Gate 1A uses a durable per-payment-attempt reconciliation control for cooldown, backoff, retry budget, circuit, exhaustion and synthetic blocking. | An in-memory/per-batch breaker cannot contain calls across worker polls or restart and cannot provide auditable operator evidence. |
| DEC-018 | 2026-11-17 | Equivalent provider-unavailable observations use a stable identity inside the retry window; observation time alone must not create new material truth. | Prevents evidence and truth-version amplification without suppressing genuinely fresh provider information. |
| DEC-019 | 2026-11-17 | Controlled synthetic identifiers are blocked before a live provider adapter. A deterministic provider stub is acceptable for Gate 1A containment/recovery tests but is never labelled live Razorpay evidence. | Keeps deterministic diagnosis cheap and safe while preserving provenance honesty. |
| DEC-020 | 2026-11-17 | Worker reconciliation counters must be visible in Safety Controls, but DOM assertions do not replace visual review. | Judge-relevant controls must be understandable; the current 1024px clipping and washed-out case capture remain explicit gaps. |
| DEC-021 | 2026-11-18 | Adopt `UNIFIED-MASTER-ROADMAP.md` as the locked consolidated product blueprint while keeping the six audit documents authoritative for current state and execution control. | Prevents the feature catalogue from overwriting evidence or historical work orders. |
| DEC-022 | 2026-11-18 | Treat M0–M8 as scope/priority crosswalks, not replacement gate numbers; preserve Gate 1A → Gate 2 → Phase 17B → Phases 18–23 order. | Avoids reversing established technical dependencies or skipping the active gate. |
| DEC-023 | 2026-11-18 | Make stale-approval prevention and revalidation immediately before execution mandatory selection-critical safety requirements. | New material payment truth must invalidate old authority before any mutation. |
| DEC-024 | 2026-11-18 | Make durable provider intent, deterministic idempotency, ambiguity classification and reconciliation-before-retry mandatory. | Provider acceptance followed by application failure must not create a duplicate action. |
| DEC-025 | 2026-11-18 | Run an early account-specific Razorpay Test Mode capability preflight before the provider-backed journey; documentation alone is insufficient. | Checkout methods, failure controls, Payment Link limits and webhook delivery can be account/product dependent. |
| DEC-026 | 2026-11-18 | Keep provider-backed Test Mode, replay and synthetic evaluation cohorts separate in storage, UI and reports. | Prevents simulated evidence from being presented as provider-backed recovery. |
| DEC-027 | 2026-11-18 | Prioritize the submission-critical path without deleting F-01–F-50; P1/P2 work may be scheduled later only through an explicit documented decision. | Payment truth, safety, one provider-backed journey, AI evidence quality and reproducibility must be completed before polish, while promised scope remains traceable. |

## Existing architectural decisions retained

The following ADRs remain authoritative unless explicitly replaced:

- `docs/decisions/0001-bounded-recovery-agent.md`
- `docs/decisions/0002-versioned-payment-truth.md`
- `docs/decisions/0003-ai-authority-boundary.md`
- `docs/decisions/0004-durable-provider-execution.md`
- `docs/decisions/0005-honest-recovery-evaluation.md`

## Unified-roadmap proposal history — approved

These proposal IDs are retained as reconciliation history. They were approved on
18 November 2026 and are locked as `DEC-021` through `DEC-027` above.

| Proposed ID | Decision | Reason |
| --- | --- | --- |
| DRAFT-UR-01 | Adopt `UNIFIED-MASTER-ROADMAP.md` as the consolidated product blueprint while keeping the six audit documents authoritative for current state and execution control. | Prevents the feature catalogue from overwriting evidence or historical work orders. |
| DRAFT-UR-02 | Treat M0–M8 as scope/priority crosswalks, not replacement gate numbers; preserve Gate 1A → Gate 2 → Phase 17B → Phases 18–23 order. | Avoids reversing established technical dependencies or skipping the active gate. |
| DRAFT-UR-03 | Make stale-approval prevention and revalidation immediately before execution mandatory selection-critical safety requirements. | New material payment truth must invalidate old authority before any mutation. |
| DRAFT-UR-04 | Make durable provider intent, deterministic idempotency, ambiguity classification and reconciliation-before-retry mandatory. | Provider acceptance followed by application failure must not create a duplicate action. |
| DRAFT-UR-05 | Run an early account-specific Razorpay Test Mode capability preflight before the provider-backed journey; documentation alone is insufficient. | Checkout methods, failure controls, Payment Link limits and webhook delivery can be account/product dependent. |
| DRAFT-UR-06 | Keep provider-backed Test Mode, replay and synthetic evaluation cohorts separate in storage, UI and reports. | Prevents simulated evidence from being presented as provider-backed recovery. |
| DRAFT-UR-07 | Prioritize the submission-critical path and defer P1/P2 polish when it competes with payment truth, safety, one provider-backed journey, AI evidence quality or reproducibility. | A smaller verified product is stronger than a broad unverified catalogue. |

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
| OPEN-009 | RESOLVED: Gate 1A remediation for `G1-P0-001` is verified and committed locally in the owner-authorized 23-path closure commit. | G1A-01 through G1A-08 pass; exact path, identity, staged-diff and post-commit checks are recorded. | Gate 2 is the next separate work order; no push is implied. |
| OPEN-010 | RESOLVED for Gate 1A: provider-emitted Razorpay Test Mode proof is deferred to the bounded provider-backed journey. | Gate 1A proves containment with deterministic provider evidence; G1-07/F-38 remain `PARTIAL` and may not be relabelled live. No feature is removed and no provider mutation is authorized. | Verify current Test Mode capabilities early in the provider-backed phase with a fixed read/mutation budget and explicit approval. |
| OPEN-011 | RESOLVED: the owner approved the reconciled unified roadmap on 18 November 2026. | DRAFT-UR-01 through DRAFT-UR-07 are locked as DEC-021 through DEC-027. | Future scope/order changes require explicit owner approval and an append-only replacement decision. |
| OPEN-012 | RESOLVED: the twenty-second path is `apps/web/src/app/globals.css`. | Its bounded responsive navigation/table/animation correction is part of the reviewed Gate 1A frontend evidence; all 22 paths remain preserved. | Keep exact-path guards at 16 application/test/frontend paths plus the authority-document set. |
