# ReclaimRail judge-experience contract

Status: locked for implementation after the backend lifecycle API is stable.

## Governing rule

The interface never invents progress. It reveals real backend evidence clearly,
sequentially and at a readable scale.

## Demo modes

1. **Guided provider run**: Netbanking failure by default, fixed INR 3,499 amount,
   contact prefill, selected method first, approximately two or three provider clicks.
2. **Verified one-click replay**: zero-input replay of a previously completed real
   Razorpay Test Mode evidence chain, clearly labelled as a replay.
3. **Custom investigation**: selectable amount, method, intended scenario, incident and
   review conditions with availability validation before Checkout opens.

The application may prefill supported customer contact fields and configure Razorpay's
method order. It must not claim that it can enter card, CVV, OTP or UPI credentials, or
choose provider success and failure on the judge's behalf. An unavailable selected method
must never silently fall back to Card.

## Live presentation

- The backend starts recovery only from signed provider evidence, never from browser
  return or Checkout callbacks.
- A five-second backend stabilization deadline is shown as a real countdown.
- Events received while Checkout is open are replayed in their original timestamp order
  after return, without changing their persisted state.
- The active stage owns the visible viewport. Completed stages collapse to readable
  summaries; a `Follow live` control returns focus after manual inspection.
- Waiting for customer/provider evidence is not displayed as active automation.
- No spinner may continue indefinitely; timeout diagnostics show last evidence, worker
  health and the safe next action.

## Information architecture

- Live Recovery
- Command Center
- Recovery Cases
- Human Reviews
- Rail Intelligence
- Batch Evaluation
- Outcome Ledger
- Audit & Controls

## Visual baseline

- Inter for interface text and JetBrains Mono for evidence identifiers.
- 40--44 px page titles, 24--28 px section titles, 19--21 px workflow titles, 17 px body
  text, and no important text below 14 px.
- High-contrast navy, blue, emerald, amber, red, purple and provider-cyan state tokens.
- Lucide icons with an icon, label and colour for every state.
- A fluid desktop layout with no ordinary horizontal scrolling at 100% or 125% scaling.
- Clear whitespace and hierarchy instead of equal nested boxes.

## Truthful money rules

- Original success ends with `No recovery required` and shows no failure or agent stages.
- An unpaid recovery link shows `Recovery pending` and zero recovered.
- Recovery is counted only after provider confirmation.
- Duplicate prevention appears only when a stopping or idempotency event proves it.
- Provider-backed and synthetic evaluation money are never combined.

## Frontend release gates

- Selected method opens first and never silently changes.
- The newest live case is pinned in the Command Center.
- Active evidence is visible without scrolling.
- Timestamps and durations are monotonic and backend-derived.
- Human review and incident effects are visible and operable.
- Charts expose exact totals, provenance, tooltips and textual summaries.
- Keyboard, contrast, 1024 px, 1440 px and 1920 px layouts pass.
- The complete judge story can be demonstrated in five minutes.
