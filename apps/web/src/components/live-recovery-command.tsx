"use client";

import {
  ArrowRight,
  Check,
  ClipboardCheck,
  Clock3,
  Copy,
  ExternalLink,
  Link2,
  LoaderCircle,
  MailCheck,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { LiveElapsed } from "@/components/live-time";
import { type PaymentLabLiveRun } from "@/hooks/use-payment-lab-live-run";
import { formatMoney, formatTimestamp } from "@/lib/presentation";

type CheckoutRun = {
  payment_lab_run_id: string;
  checkout: {
    amount_minor: number;
    currency: string;
    order_id: string;
  };
};

type LiveRecoveryCommandProps = {
  run: CheckoutRun;
  liveRun: PaymentLabLiveRun | null;
  polling: boolean;
  title: string;
  detail: string;
  safeError: string | null;
  pollError: string | null;
  webhookDelayWarning: string | null;
  runState: string;
  copiedActionId: string | null;
  onCopyRecoveryLink: () => void;
  onStartAnotherRun: () => void;
};

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function statusLabel(status: PaymentLabLiveRun["steps"][number]["status"]): string {
  if (status === "completed") return "Recorded";
  if (status === "active") return "In progress";
  if (status === "failed") return "Stopped safely";
  return "Waiting";
}

function messageStatusCopy(status: string | null): string {
  if (status === "direct_email_accepted") {
    return "Resend accepted the controlled email request. Acceptance is not proof that the recipient opened it.";
  }
  if (status === "notified_sms" || status === "notified_email") {
    return "Razorpay accepted the notification request. Device or inbox delivery is not claimed yet.";
  }
  if (status === "failed") {
    return "The message action stopped safely. No delivery was claimed.";
  }
  return "No provider acceptance has been recorded for a customer message yet.";
}

function confidencePercent(confidence: number | null | undefined): number | null {
  if (confidence === null || confidence === undefined || !Number.isFinite(confidence)) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round(confidence * 100)));
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1_000) return `${milliseconds} ms`;
  return `${(milliseconds / 1_000).toFixed(milliseconds < 10_000 ? 1 : 0)} s`;
}

export function LiveRecoveryCommand({
  run,
  liveRun,
  polling,
  title,
  detail,
  safeError,
  pollError,
  webhookDelayWarning,
  runState,
  copiedActionId,
  onCopyRecoveryLink,
  onStartAnotherRun,
}: LiveRecoveryCommandProps) {
  const actions = liveRun?.actions ?? [];
  const latestAction = actions.length ? actions[actions.length - 1] : null;
  const paymentLinkAction = [...actions].reverse().find(
    (action) =>
      action.action_type === "create_payment_link" &&
      action.provider_action_url !== null,
  );
  const messageAction = [...actions]
    .reverse()
    .find((action) => action.action_type === "send_recovery_message");
  const linkIsActionable = Boolean(
    paymentLinkAction &&
      (!liveRun?.outcome || liveRun.outcome.status === "payment_link_pending") &&
      !["paid", "expired", "cancelled"].includes(
        paymentLinkAction.provider_action_status ?? "",
      ),
  );
  const confidence = confidencePercent(liveRun?.agent?.ai_trace?.confidence);
  const outcome = liveRun?.outcome;
  const amount = liveRun?.amount_minor ?? run.checkout.amount_minor;
  const runStatus = polling ? "Live" : liveRun?.terminal ? "Verified" : "Waiting";
  const activeStep = liveRun?.steps.find(
    (step) => step.key === liveRun.active_step_key,
  );

  return (
    <section className="live-command" aria-live="polite" aria-label="Live recovery command">
      <header className="live-command__hero">
        <div className="live-command__eyebrow">
          <span className={`live-command__signal ${polling ? "is-live" : ""}`} aria-hidden="true" />
          <span>Provider-live evidence</span>
          <span className="live-command__badge">Razorpay Test Mode</span>
        </div>
        <div className="live-command__hero-grid">
          <div>
            <p className="live-command__amount">{formatMoney(amount)}</p>
            <h2>{liveRun?.state_label ?? title}</h2>
            <p>{liveRun?.waiting_reason ?? liveRun?.stalled_reason ?? detail}</p>
          </div>
          <dl className="live-command__run-facts">
            <div><dt>Run state</dt><dd>{runStatus}</dd></div>
            <div><dt>Elapsed</dt><dd>{liveRun ? <span className="live-command__elapsed"><Clock3 size={14} /><LiveElapsed startedAt={liveRun.created_at} endedAt={liveRun.terminal ? liveRun.updated_at : null} /></span> : "Awaiting evidence"}</dd></div>
            <div><dt>Current phase</dt><dd>{activeStep?.label ?? "Awaiting evidence"}</dd></div>
            <div><dt>Phase time</dt><dd>{activeStep?.occurred_at ? <span className="live-command__elapsed"><Clock3 size={14} /><LiveElapsed startedAt={activeStep.occurred_at} endedAt={liveRun?.terminal ? liveRun.updated_at : null} /></span> : "Not measurable yet"}</dd></div>
            <div><dt>Provider order</dt><dd title={run.checkout.order_id}>{run.checkout.order_id.slice(0, 16)}…</dd></div>
          </dl>
        </div>
      </header>

      {safeError ? <div className="live-command__notice is-error">{safeError}</div> : null}
      {pollError ? <div className="live-command__notice is-warning">{pollError}</div> : null}
      {webhookDelayWarning && runState === "awaiting_webhook" && !liveRun?.payment ? (
        <div className="live-command__notice is-warning">{webhookDelayWarning}</div>
      ) : null}

      <div className="live-command__layout">
        <section className="live-command__evidence" aria-labelledby="evidence-title">
          <div className="live-command__section-heading">
            <div><span>Evidence rail</span><h3 id="evidence-title">What actually happened</h3></div>
            <p>Events appear only after the server records them.</p>
          </div>
          {liveRun ? (
            <ol className="live-command__timeline">
              {liveRun.steps.map((step, index) => (
                <li className={`live-command__event is-${step.status}`} key={step.key}>
                  <span className="live-command__event-marker" aria-hidden="true">
                    {step.status === "completed" ? <Check size={16} strokeWidth={3} /> : step.status === "active" ? <LoaderCircle className="spin" size={16} /> : <span>{index + 1}</span>}
                  </span>
                  <div>
                    <div className="live-command__event-topline"><strong>{step.label}</strong><em>{statusLabel(step.status)}</em></div>
                    <p>{step.detail}</p>
                    {step.occurred_at ? <time dateTime={step.occurred_at}>{formatTimestamp(step.occurred_at)} IST{step.duration_milliseconds !== null ? ` · executed in ${formatDuration(step.duration_milliseconds)}` : ""}</time> : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="live-command__empty-evidence">
              <LoaderCircle className="spin" size={18} />
              Checkout is ready. ReclaimRail is waiting for signed Razorpay evidence before beginning recovery.
            </div>
          )}
        </section>

        <aside className="live-command__decision" aria-label="AI, policy, and customer action">
          <div className="live-command__decision-heading">
            <span><Sparkles size={15} /> AI proposal</span>
            <strong className={liveRun?.agent?.fallback_used ? "is-fallback" : ""}>
              {liveRun?.agent ? liveRun.agent.fallback_used ? "Deterministic fallback" : "Gemini trace" : "Awaiting evidence"}
            </strong>
          </div>
          <h3>{liveRun?.agent?.ai_trace?.recommended_action ? humanize(liveRun.agent.ai_trace.recommended_action) : "No recovery action proposed yet"}</h3>
          <p>{liveRun?.agent?.reasoning_summary ?? "AI can propose only after a signed failure is correlated. Deterministic policy remains the decision-maker."}</p>

          {liveRun?.agent ? (
            <div className="live-command__ai-source">
              <span>{liveRun.agent.planner_provider ?? "Planner"}{liveRun.agent.model_name ? ` · ${liveRun.agent.model_name}` : ""}</span>
              {liveRun.agent.fallback_reason ? <small>Fallback reason: {humanize(liveRun.agent.fallback_reason)}</small> : null}
            </div>
          ) : null}

          <dl className="live-command__decision-facts">
            <div><dt>Root cause</dt><dd>{liveRun?.agent?.ai_trace?.root_cause_category ? humanize(liveRun.agent.ai_trace.root_cause_category) : "Awaiting classification"}</dd></div>
            <div><dt>Policy result</dt><dd>{latestAction ? humanize(latestAction.policy_outcome) : "Awaiting policy"}</dd></div>
          </dl>
          {confidence !== null ? (
            <div className="live-command__confidence">
              <div><span>AI confidence</span><strong>{confidence}%</strong></div>
              <i><b style={{ width: `${confidence}%` }} /></i>
              <small>This expresses assessment confidence, not payment likelihood.</small>
            </div>
          ) : null}
          {latestAction?.policy_guardrails.length ? (
            <ul className="live-command__guardrails">
              {latestAction.policy_guardrails.map((guardrail) => <li key={guardrail}><ShieldCheck size={14} /> {humanize(guardrail)}</li>)}
            </ul>
          ) : null}
          {liveRun?.agent?.ai_trace && (liveRun.agent.ai_trace.evidence_codes.length > 0 || liveRun.agent.ai_trace.evidence_tool_names.length > 0) ? (
            <div className="live-command__ai-evidence">
              <span>Evidence AI could inspect</span>
              <ul>
                {[...liveRun.agent.ai_trace.evidence_codes, ...liveRun.agent.ai_trace.evidence_tool_names].map((evidence, index) => <li key={`${evidence}-${index}`}>{humanize(evidence)}</li>)}
              </ul>
            </div>
          ) : null}
          {liveRun?.approval ? (
            <div className="live-command__approval"><ShieldAlert size={16} /><span><strong>Human review {humanize(liveRun.approval.status)}</strong>{liveRun.approval.decision_reason ?? liveRun.approval.request_reason}</span></div>
          ) : null}
        </aside>
      </div>

      <div className="live-command__actions-grid">
        <section className="live-command__customer-action" aria-label="Customer recovery message">
          <div className="live-command__panel-kicker"><MailCheck size={16} /> Customer message{messageAction?.channel ? ` · ${humanize(messageAction.channel)}` : ""}</div>
          <h3>{messageAction ? humanize(messageAction.provider_action_status ?? messageAction.status) : "Not sent yet"}</h3>
          <p>{messageStatusCopy(messageAction?.provider_action_status ?? null)}</p>
          <small>Recipient details stay protected. Direct email uses the consented allowlisted demo inbox; SMS requires a consented customer mobile record and Razorpay acceptance.</small>
        </section>

        <section className="live-command__customer-action live-command__customer-action--link" aria-label="Recovery payment link">
          <div className="live-command__panel-kicker"><Link2 size={16} /> Provider payment link</div>
          <h3>{paymentLinkAction ? linkIsActionable ? "Ready for customer action" : humanize(paymentLinkAction.provider_action_status ?? "recorded") : "Not created yet"}</h3>
          <p>{paymentLinkAction ? `Razorpay link ${paymentLinkAction.provider_action_id ? paymentLinkAction.provider_action_id.slice(0, 16) : "pending"} · ${paymentLinkAction.provider_action_expires_at ? `expires ${formatTimestamp(paymentLinkAction.provider_action_expires_at)} IST` : "provider-managed expiry"}` : "A link is created only if deterministic policy authorizes it."}</p>
          {linkIsActionable && paymentLinkAction?.provider_action_url ? (
            <div className="live-command__link-actions">
              <a href={paymentLinkAction.provider_action_url} target="_blank" rel="noreferrer noopener">Open Test Link <ExternalLink size={15} /></a>
              <button type="button" onClick={onCopyRecoveryLink}><Copy size={15} />{copiedActionId === paymentLinkAction.recovery_action_id ? "Copied" : "Copy link"}</button>
            </div>
          ) : null}
        </section>

        <section className={`live-command__outcome ${outcome ? `is-${outcome.status}` : ""}`} aria-label="Verified financial outcome">
          <div className="live-command__panel-kicker"><ShieldCheck size={16} /> Financial outcome</div>
          <h3>{outcome ? humanize(outcome.status) : "Not counted yet"}</h3>
          <p>{outcome?.status === "recovered" ? `${formatMoney(outcome.gross_recovered_minor)} is backed by provider reconciliation and a ledger event.` : outcome?.status === "duplicate_collection_prevented" ? `${formatMoney(outcome.duplicate_collection_prevented_minor)} was protected after reconciliation.` : "Opening a link, sending a message, or a browser callback never counts as recovered revenue."}</p>
        </section>
      </div>

      <footer className="live-command__footer">
        <span><ShieldCheck size={16} /> Truth rule: signed webhooks and provider reconciliation, never browser claims, determine the result.</span>
        <div>
          {liveRun?.agent ? <Link href={`/cases/${liveRun.agent.recovery_case_id}`}><ClipboardCheck size={16} /> Case evidence</Link> : null}
          <Link href={liveRun?.agent ? `/?liveCase=${liveRun.agent.recovery_case_id}#recovery-queue` : "/"}>Command center <ArrowRight size={16} /></Link>
          {liveRun?.terminal ? <button type="button" onClick={onStartAnotherRun}>Start another run</button> : null}
        </div>
      </footer>
    </section>
  );
}
