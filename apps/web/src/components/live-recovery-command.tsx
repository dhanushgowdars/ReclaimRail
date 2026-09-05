"use client";

import { ArrowRight, ClipboardCheck, Clock3, Copy, ExternalLink, Link2, LoaderCircle, MailCheck, PlayCircle, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { LinkExpiryCountdown, LiveElapsed } from "@/components/live-time";
import { type PaymentLabLiveRun } from "@/hooks/use-payment-lab-live-run";
import { formatMoney, formatTimestamp } from "@/lib/presentation";

type CheckoutRun = { payment_lab_run_id: string; checkout: { amount_minor: number; currency: string; order_id: string } };
type LiveRecoveryCommandProps = {
  run: CheckoutRun;
  liveRun: PaymentLabLiveRun | null;
  polling: boolean;
  title: string;
  detail: string;
  safeError: string | null;
  pollError: string | null;
  webhookDelayWarning: string | null;
  isVerifiedReplay: boolean;
  copiedActionId: string | null;
  onCopyRecoveryLink: () => void;
  onOpenVerifiedReplay: () => void;
  onOpenCheckout: () => void;
  onStartAnotherRun: () => void;
  approvingApprovalId: string | null;
  approvalError: string | null;
  onApprovalDecision: (decision: "approve" | "reject", reason: string) => void;
};

function humanize(value: string): string { return value.replaceAll("_", " "); }
function statusLabel(status: PaymentLabLiveRun["steps"][number]["status"]): string {
  if (status === "completed") return "Recorded";
  if (status === "active") return "In progress";
  if (status === "failed") return "Stopped safely";
  return "Waiting";
}
function formatDuration(milliseconds: number): string {
  return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
}
function hasExpired(value: string | null): boolean {
  return value !== null && Number.isFinite(Date.parse(value)) && Date.parse(value) <= Date.now();
}
function messageStatusCopy(status: string | null): string {
  if (status === "direct_email_accepted") return "Resend accepted the controlled email request. Inbox delivery is not claimed.";
  if (status === "notified_sms" || status === "notified_email") return "Razorpay accepted the notification request. Device or inbox delivery is not claimed.";
  if (status === "failed") return "The message action stopped safely. No delivery was claimed.";
  return "No provider acceptance has been recorded for a customer message yet.";
}

export function LiveRecoveryCommand({ run, liveRun, polling, title, detail, safeError, pollError, webhookDelayWarning, isVerifiedReplay, copiedActionId, onCopyRecoveryLink, onOpenVerifiedReplay, onOpenCheckout, onStartAnotherRun, approvingApprovalId, approvalError, onApprovalDecision }: LiveRecoveryCommandProps) {
  const activeEventRef = useRef<HTMLLIElement | null>(null);
  const lastActiveStep = useRef<string | null>(null);
  const actions = liveRun?.actions ?? [];
  const latestAction = actions.at(-1) ?? null;
  const approvalActionLabel = humanize(latestAction?.action_type ?? "recovery action");
  const paymentLinkAction = [...actions].reverse().find((action) => action.action_type === "create_payment_link" && action.provider_action_url !== null);
  const messageAction = [...actions].reverse().find((action) => action.action_type === "send_recovery_message");
  const approvalClosed = liveRun?.approval?.status === "rejected" || liveRun?.approval?.status === "expired";
  const outcome = liveRun?.outcome;
  const amount = liveRun?.amount_minor ?? run.checkout.amount_minor;
  const activeStep = liveRun?.steps.find((step) => step.key === liveRun.active_step_key);
  const activeStepIndex = liveRun?.steps.findIndex((step) => step.key === liveRun.active_step_key) ?? -1;
  const recordedStepCount = liveRun?.steps.filter((step) => step.status === "completed").length ?? 0;
  const runStatus = isVerifiedReplay ? "Replay" : polling ? "Live" : liveRun?.terminal ? "Verified" : "Waiting";
  const linkExpired = hasExpired(paymentLinkAction?.provider_action_expires_at ?? null);
  const linkIsActionable = Boolean(paymentLinkAction && !linkExpired && (!outcome || outcome.status === "payment_link_pending") && !["paid", "expired", "cancelled"].includes(paymentLinkAction.provider_action_status ?? ""));
  const recommendedAction = liveRun?.agent?.ai_trace?.recommended_action ?? latestAction?.action_type ?? null;
  const operatorExplanation = liveRun?.agent?.ai_trace?.operator_explanation ?? null;
  const fallbackUsed = Boolean(liveRun?.agent?.fallback_used);
  const decisionFinding = liveRun?.agent?.ai_trace?.root_cause_category
    ?? (fallbackUsed ? liveRun?.payment?.failure_reason ?? liveRun?.payment?.failure_code ?? "verified payment failure" : null);
  const heroDetail = isVerifiedReplay
    ? "This is a completed, provider-backed Test Mode run. It does not change the active run or add revenue."
    : outcome?.status === "recovered"
      ? "Razorpay confirmed recovered revenue for this run."
      : liveRun?.terminal
        ? "The run is closed. Its final state is backed by persisted provider and policy evidence."
        : liveRun?.waiting_reason ?? liveRun?.stalled_reason ?? detail;
  const showLiveActivity = Boolean(liveRun && !liveRun.terminal && !isVerifiedReplay);
  const canOpenCheckout = !isVerifiedReplay && !liveRun?.terminal && !liveRun?.payment;
  const activityStatus = pollError
    ? "Retrying evidence check"
    : webhookDelayWarning
      ? "Waiting on provider"
      : activeStep
        ? "Server work active"
        : "Awaiting next evidence";
  const activityDetail = activeStep?.detail
    ?? liveRun?.waiting_reason
    ?? liveRun?.stalled_reason
    ?? "ReclaimRail is checking for the next persisted evidence transition.";
  const approvalNote = liveRun?.approval?.decision_reason === "nothing"
    ? "No decision note supplied"
    : liveRun?.approval?.decision_reason ?? liveRun?.approval?.request_reason;
  const [approvalReason, setApprovalReason] = useState("");

  useEffect(() => {
    if (!liveRun?.active_step_key || lastActiveStep.current === liveRun.active_step_key) return;
    lastActiveStep.current = liveRun.active_step_key;
    activeEventRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [liveRun?.active_step_key]);

  return <section className="live-command" aria-live="polite" aria-label="Continuous live recovery workflow">
    <header className="live-command__hero">
      <div className="live-command__eyebrow"><span className={`live-command__signal ${polling && !isVerifiedReplay ? "is-live" : ""}`} aria-hidden="true" /><span>{isVerifiedReplay ? "Verified replay · recorded Test Mode run" : "Provider-live evidence"}</span><span className="live-command__badge">Razorpay Test Mode</span></div>
      <div className="live-command__hero-grid"><div><p className="live-command__amount">{formatMoney(amount)}</p><h2>{isVerifiedReplay ? "Verified recovery replay" : liveRun?.state_label ?? title}</h2><p>{heroDetail}</p></div>
        <dl className="live-command__run-facts"><div><dt>Run state</dt><dd>{runStatus}</dd></div><div><dt>Elapsed</dt><dd>{liveRun ? <span className="live-command__elapsed"><Clock3 size={14} /><LiveElapsed startedAt={liveRun.created_at} endedAt={liveRun.terminal ? liveRun.updated_at : null} /></span> : "Awaiting evidence"}</dd></div><div><dt>Live step</dt><dd>{activeStep?.label ?? (liveRun?.terminal ? "Run complete" : "Awaiting evidence")}</dd></div><div><dt>Step time</dt><dd>{activeStep?.occurred_at ? <span className="live-command__elapsed"><Clock3 size={14} /><LiveElapsed startedAt={activeStep.occurred_at} endedAt={null} /></span> : liveRun?.terminal ? "Complete" : "Not measurable yet"}</dd></div><div><dt>Provider order</dt><dd title={run.checkout.order_id}>{run.checkout.order_id.slice(0, 16)}…</dd></div></dl>
      </div>
    </header>
    {safeError ? <div className="live-command__notice is-error">{safeError}</div> : null}
    {pollError ? <div className="live-command__notice is-warning">{pollError}</div> : null}
    {webhookDelayWarning && !isVerifiedReplay ? <div className="live-command__notice is-warning live-command__replay-notice"><div><strong>Waiting for Razorpay longer than usual.</strong><span>{webhookDelayWarning}</span></div><button type="button" onClick={onOpenVerifiedReplay}><PlayCircle size={16} /> Open verified replay</button></div> : null}
    {showLiveActivity ? <section className="live-command__active-work" aria-label="Live server work">
      <span className="live-command__active-icon"><LoaderCircle className="spin" size={21} /></span>
      <div><p>Live work in progress</p><h3>{activeStep?.label ?? liveRun?.state_label ?? "Waiting for evidence"}</h3><span>{activityDetail}</span></div>
      <dl><div><dt>Status</dt><dd>{activityStatus}</dd></div><div><dt>Evidence progress</dt><dd>{liveRun ? `${recordedStepCount} recorded · phase ${activeStepIndex >= 0 ? activeStepIndex + 1 : "waiting"} active` : "Awaiting first event"}</dd></div><div><dt>Responsible worker</dt><dd>{liveRun?.responsible_worker ? humanize(liveRun.responsible_worker) : "Provider evidence pipeline"}</dd></div><div><dt>Worker health</dt><dd>{liveRun?.responsible_worker_status ? humanize(liveRun.responsible_worker_status) : polling ? "Connected" : "Awaiting update"}</dd></div>{activeStep?.occurred_at ? <div><dt>Active for</dt><dd><LiveElapsed startedAt={activeStep.occurred_at} endedAt={null} /></dd></div> : null}</dl>
      {canOpenCheckout ? <button className="live-command__resume-checkout" type="button" onClick={onOpenCheckout}><PlayCircle size={16} /> Open Razorpay Checkout</button> : null}
    </section> : null}

    <div className="live-command__layout live-command__layout--continuous">
      <section className="live-command__evidence" aria-labelledby="evidence-title"><div className="live-command__section-heading"><div><span>{isVerifiedReplay ? "Recorded recovery workflow" : "Continuous recovery workflow"}</span><h3 id="evidence-title">Watch evidence arrive in business order</h3></div><p>No step is animated or manually advanced. Entries appear only after the server records evidence.</p></div>
        {liveRun ? <ol className="live-command__timeline">{liveRun.steps.map((step, index) => <li ref={step.key === liveRun.active_step_key ? activeEventRef : undefined} className={`live-command__event is-${step.status}${step.key === liveRun.active_step_key ? " is-current" : ""}`} key={step.key}><span className="live-command__event-marker" aria-label={`Step ${index + 1}: ${statusLabel(step.status)}`}>{index + 1}</span><div><div className="live-command__event-topline"><div><span className="live-command__event-number">Step {index + 1}</span><strong>{step.label}</strong></div><em>{step.status === "active" ? <LoaderCircle className="spin" size={12} /> : null}{statusLabel(step.status)}</em></div><p>{step.detail}</p>{step.occurred_at ? <time dateTime={step.occurred_at}>{formatTimestamp(step.occurred_at)} IST{step.duration_milliseconds !== null ? ` · completed in ${formatDuration(step.duration_milliseconds)}` : ""}</time> : null}</div></li>)}</ol> : <div className="live-command__empty-evidence"><LoaderCircle className="spin" size={18} /> Checkout is ready. ReclaimRail is waiting for server-verified Razorpay evidence before beginning recovery.</div>}
      </section>
      <aside className="live-command__decision" aria-label="Recovery decision brief"><div className="live-command__decision-heading"><span><Sparkles size={15} /> AI recommendation under control</span><strong className={fallbackUsed ? "is-fallback" : ""}>{liveRun?.agent ? fallbackUsed ? "Deterministic fallback" : "Gemini proposal" : "Awaiting evidence"}</strong></div><h3>{recommendedAction ? `Propose: ${humanize(recommendedAction)}` : "No action proposed yet"}</h3><p>{liveRun?.agent?.reasoning_summary ?? "Gemini can propose only after a signed failure is correlated. Deterministic policy remains the decision-maker."}</p>
        {liveRun?.agent ? <div className="live-command__ai-source"><span>{liveRun.agent.planner_provider ?? "Planner"}{liveRun.agent.model_name ? ` · ${liveRun.agent.model_name}` : ""}</span>{liveRun.agent.fallback_reason ? <small>Fallback reason: {humanize(liveRun.agent.fallback_reason)}</small> : null}</div> : null}
        <div className="live-command__ai-readout"><article><span>What Gemini observed</span><strong>{decisionFinding ? humanize(decisionFinding) : "Waiting for signed provider evidence"}</strong></article><article><span>What it proposes</span><strong>{recommendedAction ? humanize(recommendedAction) : "No action"}</strong></article><article><span>What controls execution</span><strong>Deterministic policy and authorised human review</strong></article></div>
        <dl className="live-command__decision-facts"><div><dt>{fallbackUsed ? "Verified failure evidence" : "What AI found"}</dt><dd>{decisionFinding ? humanize(decisionFinding) : "Waiting for provider evidence"}</dd></div><div><dt>Evidence source</dt><dd>{liveRun?.payment ? humanize(liveRun.payment.source ?? "signed_webhook") : "Awaiting provider verification"}</dd></div><div><dt>Safety decision</dt><dd>{latestAction ? humanize(latestAction.policy_outcome) : "Waiting for deterministic policy"}</dd></div></dl>
        {operatorExplanation ? <p className="live-command__operator-explanation"><b>Why this recommendation:</b> {operatorExplanation}</p> : null}
        {liveRun?.agent?.ai_trace?.evidence_citations.length ? <div className="live-command__citations"><b>Evidence cited by the planner</b>{liveRun.agent.ai_trace.evidence_citations.map((citation) => <div key={citation.reference}><strong>{citation.label}</strong><span>{citation.observations.join(" · ")}</span></div>)}</div> : null}
        {liveRun?.agent?.ai_trace?.reasoning_items.length ? <div className="live-command__citations"><b>Evidence-cited decision trace</b>{liveRun.agent.ai_trace.reasoning_items.map((item, index) => <div key={`${item.interpretation}-${index}`}><strong>{item.interpretation}</strong><span><b>Effect on this plan:</b> {item.action_impact}</span></div>)}</div> : null}
        {liveRun?.agent?.ai_trace?.alternatives_considered.length ? <div className="live-command__citations"><b>Alternatives evaluated</b>{liveRun.agent.ai_trace.alternatives_considered.map((item) => <div key={`${item.action_type}-${item.disposition}`}><strong>{humanize(item.action_type)}</strong><span>{item.reason}</span></div>)}</div> : null}
        {liveRun?.agent?.ai_trace?.known_uncertainties.length ? <p className="live-command__operator-explanation"><b>Known uncertainty:</b> {liveRun.agent.ai_trace.known_uncertainties.join(" ")}</p> : null}
        {actions.length ? <div className="live-command__planned-actions"><span>Policy-reviewed recovery plan</span>{actions.map((action) => <div key={action.recovery_action_id}><strong>{humanize(action.action_type)}</strong><p>{action.proposal_reason}</p><em>Policy: {humanize(action.policy_outcome)}</em></div>)}</div> : null}
        {latestAction?.policy_guardrails.length ? <ul className="live-command__guardrails">{latestAction.policy_guardrails.map((guardrail) => <li key={guardrail}><ShieldCheck size={14} /> {humanize(guardrail)}</li>)}</ul> : null}
        {liveRun?.approval ? <div className="live-command__approval"><ShieldAlert size={16} /><span><strong>Protected review {humanize(liveRun.approval.status)}</strong>{approvalNote}</span>{liveRun.approval.status === "pending" && !isVerifiedReplay ? <div className="live-command__approval-controls"><p>This is a risk exception, not an AI override. Approving permits only this already-allowed action; hard policy stops remain blocked.</p><label>Decision note<input value={approvalReason} maxLength={300} onChange={(event) => setApprovalReason(event.target.value)} placeholder="Optional reason for the audit trail" /></label>{approvalError ? <small className="live-command__approval-error">{approvalError}</small> : null}<div><button type="button" disabled={approvingApprovalId === liveRun.approval.approval_id} onClick={() => onApprovalDecision("approve", approvalReason)}>{approvingApprovalId === liveRun.approval.approval_id ? "Recording decision…" : `Approve ${approvalActionLabel}`}</button><button className="is-secondary" type="button" disabled={approvingApprovalId === liveRun.approval.approval_id} onClick={() => onApprovalDecision("reject", approvalReason)}>Decline {approvalActionLabel}</button></div></div> : null}</div> : null}
      </aside>
    </div>
    <div className="live-command__actions-grid"><section className="live-command__customer-action" aria-label="Customer recovery message"><div className="live-command__panel-kicker"><MailCheck size={16} /> Customer message{messageAction?.channel ? ` · ${humanize(messageAction.channel)}` : ""}</div><h3>{approvalClosed && !messageAction?.provider_action_status ? "Not executed" : messageAction?.provider_action_status ? humanize(messageAction.provider_action_status) : messageAction ? "Allowed by policy · not sent" : "Not sent yet"}</h3><p>{approvalClosed && !messageAction?.provider_action_status ? "The protected decision closed before any message provider accepted a request." : messageStatusCopy(messageAction?.provider_action_status ?? null)}</p><small>Recipient details stay protected. Direct email uses the consented allowlisted demo inbox; SMS needs a consented customer mobile record and provider acceptance.</small></section>
      <section className="live-command__customer-action live-command__customer-action--link" aria-label="Recovery payment link"><div className="live-command__panel-kicker"><Link2 size={16} /> Provider payment link</div><h3>{paymentLinkAction ? linkExpired ? "Expired — payment disabled" : linkIsActionable ? "Ready for customer action" : humanize(paymentLinkAction.provider_action_status ?? "recorded") : "Not created yet"}</h3><p>{paymentLinkAction ? `Razorpay link ${paymentLinkAction.provider_action_id ? paymentLinkAction.provider_action_id.slice(0, 16) : "pending"} · ${paymentLinkAction.provider_action_expires_at ? `Expires on ${formatTimestamp(paymentLinkAction.provider_action_expires_at)} IST` : "provider-managed expiry"}` : "A link is created only when deterministic policy allows it."}</p>{linkIsActionable && paymentLinkAction?.provider_action_expires_at ? <small className="live-command__expiry"><LinkExpiryCountdown expiresAt={paymentLinkAction.provider_action_expires_at} /> · Razorpay records the final payment, expiry, or cancellation.</small> : null}{linkExpired ? <small>ReclaimRail has removed payment access after the recorded provider expiry. The next Razorpay confirmation records the final provider status.</small> : null}{linkIsActionable && paymentLinkAction?.provider_action_url ? <div className="live-command__link-actions"><a href={paymentLinkAction.provider_action_url} target="_blank" rel="noreferrer noopener">Open Test Link <ExternalLink size={15} /></a><button type="button" onClick={onCopyRecoveryLink}><Copy size={15} />{copiedActionId === paymentLinkAction.recovery_action_id ? "Copied" : "Copy link"}</button></div> : null}</section>
      <section className={`live-command__outcome ${outcome ? `is-${outcome.status}` : ""}`} aria-label="Verified financial outcome"><div className="live-command__panel-kicker"><ShieldCheck size={16} /> Financial outcome</div><h3>{outcome ? humanize(outcome.status) : "Not counted yet"}</h3><p>{outcome?.status === "recovered" ? `${formatMoney(outcome.gross_recovered_minor)} is backed by Razorpay payment confirmation and a ledger event.` : outcome?.status === "duplicate_collection_prevented" ? `${formatMoney(outcome.duplicate_collection_prevented_minor)} was protected after provider confirmation.` : "Opening a link, sending a message, or a browser callback never counts as recovered revenue."}</p></section>
    </div>
    <footer className="live-command__footer"><span><ShieldCheck size={16} /> Truth rule: Razorpay provider evidence, never browser claims, determines the payment result.</span><div>{liveRun?.agent ? <Link href={`/cases/${liveRun.agent.recovery_case_id}`}><ClipboardCheck size={16} /> Case evidence</Link> : null}<Link href={liveRun?.agent ? `/?liveCase=${liveRun.agent.recovery_case_id}#recovery-queue` : "/"}>Command center <ArrowRight size={16} /></Link>{liveRun || isVerifiedReplay ? <button type="button" onClick={onStartAnotherRun}>{liveRun && !liveRun.terminal && !isVerifiedReplay ? "Start another run · leave this link active" : "Start another run"}</button> : null}</div></footer>
  </section>;
}
