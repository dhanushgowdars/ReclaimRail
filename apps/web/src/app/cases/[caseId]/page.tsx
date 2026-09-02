import { ArrowLeft, ArrowUpRight, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { CaseEvidenceTabs } from "@/components/case-evidence-tabs";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import {
  type RecoveryCaseDetail,
  loadRecoveryCaseDetail,
} from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, titleCase } from "@/lib/presentation";

export const dynamic = "force-dynamic";

function shortValue(value: string): string {
  return value.length <= 12 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

function badgeTone(value: string): string {
  if (["recovered", "succeeded", "allow", "allowed", "open"].includes(value)) return "success";
  if (["blocked", "cancelled", "escalated", "failed", "stopped"].includes(value)) return "danger";
  if (["waiting", "executing", "scheduled", "payment_link_pending"].includes(value)) return "warning";
  if (value === "duplicate_collection_prevented") return "protected";
  return "neutral";
}

function Badge({ value }: { value: string }) {
  return <span className={`badge badge--${badgeTone(value)}`}>{titleCase(value)}</span>;
}

function DetailCard({ children, title, eyebrow }: { children: React.ReactNode; title: string; eyebrow: string }) {
  return <section className="detail-card"><p className="kicker">{eyebrow}</p><h2>{title}</h2>{children}</section>;
}

function FailureContext({ detail }: { detail: RecoveryCaseDetail }) {
  const payment = detail.payment_lifecycle;
  const recoveryCase = detail.recovery_case;
  const failureReason = payment.error_reason ?? payment.error_step ?? payment.error_code ?? "Provider reported a payment failure";

  return <DetailCard eyebrow="Payment failure" title="Failure context">
    <dl className="fact-grid">
      <div><dt>Payment method</dt><dd>{payment.payment_method === null ? "Unknown" : titleCase(payment.payment_method)}</dd></div>
      <div><dt>Amount</dt><dd>{formatMoney(payment.amount_minor, payment.currency)}</dd></div>
      <div><dt>Payment state</dt><dd><Badge value={payment.current_state} /></dd></div>
      <div><dt>Recovery eligibility</dt><dd>{payment.recovery_eligible ? "Eligible at failure" : "Not eligible"}</dd></div>
      <div className="fact-grid__wide"><dt>Failure reason</dt><dd>{titleCase(failureReason)}</dd></div>
      <div className="fact-grid__wide"><dt>Late authorization</dt><dd>{recoveryCase.late_authorization_detected_at === null ? "Not detected" : formatTimestamp(recoveryCase.late_authorization_detected_at)}</dd></div>
    </dl>
  </DetailCard>;
}

function DecisionTrace({ detail }: { detail: RecoveryCaseDetail }) {
  const latestRun = [...detail.agent_runs].sort((left, right) => right.run_number - left.run_number)[0];
  return <DetailCard eyebrow="AI decision trace" title="Recommendation under control">
    <div className="decision-provider"><span>Planner</span><strong>{latestRun === undefined ? "No planning run" : titleCase(latestRun.planner_provider)}</strong></div>
    <p className="decision-summary">{latestRun?.reasoning_summary ?? "No planner reasoning is available for this case."}</p>
    <div className="decision-actions">
      {detail.actions.length === 0 ? <p>No proposed recovery actions.</p> : detail.actions.map((action) => <div className="decision-action" key={action.recovery_action_id}>
        <div><strong>{titleCase(action.action_type)}</strong><span>{action.proposal_reason}</span></div><Badge value={action.policy_outcome} />
      </div>)}
    </div>
  </DetailCard>;
}

function PolicyExecution({ detail }: { detail: RecoveryCaseDetail }) {
  const latestAction = [...detail.actions].sort((left, right) => right.sequence_number - left.sequence_number)[0];
  const uniqueGuardrails = [...new Set(detail.actions.flatMap((action) => action.policy_guardrails))];
  const policyOutcome = latestAction?.policy_outcome ?? "not_evaluated";
  const policyExplanation = latestAction?.policy_explanation ?? "No deterministic policy decision was persisted.";
  return <DetailCard eyebrow="Deterministic policy" title="Guardrails evaluated before execution">
    <div className="policy-status"><span className={`policy-status__dot policy-status__dot--${badgeTone(policyOutcome)}`} /><div><strong>{titleCase(policyOutcome)}</strong><p>{policyExplanation}</p></div></div>
    <ul className="guardrail-list">{uniqueGuardrails.length === 0 ? <li>No guardrail codes were persisted.</li> : uniqueGuardrails.map((guardrail) => <li key={guardrail}>{titleCase(guardrail)}</li>)}</ul>
  </DetailCard>;
}

function ProviderActions({ detail }: { detail: RecoveryCaseDetail }) {
  return <DetailCard eyebrow="Provider execution" title="Bounded Razorpay actions">
    <div className="action-list">{detail.actions.length === 0 ? <p>No recovery actions were persisted.</p> : detail.actions.map((action) => <article className="provider-action" key={action.recovery_action_id}>
      <div className="provider-action__heading"><div><strong>{action.sequence_number}. {titleCase(action.action_type)}</strong><span>{action.execution_attempt_count} execution attempt{action.execution_attempt_count === 1 ? "" : "s"}</span></div><Badge value={action.status} /></div>
      <dl><div><dt>Provider reference</dt><dd className="mono-value">{action.provider_action_id ?? "Not created"}</dd></div><div><dt>Provider status</dt><dd>{action.provider_action_status === null ? "Not available" : titleCase(action.provider_action_status)}</dd></div><div><dt>Expires</dt><dd>{action.provider_action_expires_at === null ? "Provider managed" : formatTimestamp(action.provider_action_expires_at)}</dd></div><div><dt>Recovery link</dt><dd>{action.provider_action_status === "paid" ? "Paid — recovery complete" : action.provider_action_url === null ? "Not created" : <a className="provider-action__link" href={action.provider_action_url} target="_blank" rel="noreferrer noopener">Open hosted Razorpay Test Link <ArrowUpRight size={16} /></a>}</dd></div></dl>
    </article>)}</div>
  </DetailCard>;
}

function OutcomeProof({ detail }: { detail: RecoveryCaseDetail }) {
  const outcome = detail.outcome;
  if (outcome === null) return <DetailCard eyebrow="Outcome proof" title="Awaiting provider evidence"><p className="detail-empty">No verified recovery outcome has been reconciled for this case yet.</p></DetailCard>;
  const recovered = outcome.gross_recovered_minor - outcome.reversed_minor;
  const isRecovered = recovered > 0;
  const duplicatePrevented = outcome.status === "duplicate_collection_prevented";
  const pending = outcome.status === "payment_link_pending";
  const amount = isRecovered ? recovered : duplicatePrevented ? outcome.duplicate_collection_prevented_minor : 0;
  const title = pending ? "Awaiting recovery-link payment" : "Verified reconciliation result";
  const amountClass = isRecovered ? "outcome-proof__money outcome-proof__money--recovered" : duplicatePrevented ? "outcome-proof__money outcome-proof__money--protected" : "outcome-proof__money";
  const amountLabel = isRecovered ? "Verified recovered" : duplicatePrevented ? "Duplicate collection prevented" : "Recovered so far";
  return <DetailCard eyebrow="Outcome proof" title={title}>
    <div className="outcome-proof"><Badge value={outcome.status} /><strong className={amountClass}>{formatMoney(amount, detail.recovery_case.currency)}</strong><span>{amountLabel}</span>{pending ? <p className="outcome-proof__waiting">The Test Payment Link exists, but Razorpay has not confirmed a recovery payment.</p> : null}</div>
    <dl className="outcome-facts"><div><dt>Attribution</dt><dd>{titleCase(outcome.attribution)}</dd></div><div><dt>Evidence</dt><dd>{outcome.evidence_event_count} linked events</dd></div><div><dt>Occurred</dt><dd>{formatTimestamp(outcome.occurred_at)}</dd></div></dl>
  </DetailCard>;
}

function AuditTimeline({ detail }: { detail: RecoveryCaseDetail }) {
  function eventLabel(event: RecoveryCaseDetail["audit_chain"]["events"][number]): string {
    if (event.event_type !== "outcome.payment_link.reconciled") return titleCase(event.event_type);
    const providerStatus = event.provider_status;
    if (providerStatus === "paid") return "Recovery payment reconciled";
    if (providerStatus === "created") return "Payment link observed — awaiting payment";
    if (typeof providerStatus === "string") return `Payment link observed — ${titleCase(providerStatus)}`;
    return "Payment link reconciliation recorded";
  }
  return <section className="audit-timeline"><div className="audit-timeline__heading"><div className="audit-timeline__title"><span><ShieldCheck size={22} /></span><div><p className="kicker">Tamper-evident audit chain</p><h2>Decision and outcome evidence</h2></div></div><Badge value={detail.audit_chain.valid ? "succeeded" : "failed"} /></div>
    <p className="audit-timeline__intro">{detail.audit_chain.valid ? `${detail.audit_chain.checked_event_count} linked events verified with ${detail.audit_chain.events[0]?.hash_algorithm ?? "the configured"} hash chain.` : detail.audit_chain.reason}</p>
    <ol>{detail.audit_chain.events.map((event) => <li key={event.sequence_number}><span className="timeline-marker" /><div className="timeline-event"><div><strong>{eventLabel(event)}</strong><span>{titleCase(event.actor_type)} · {formatTimestamp(event.occurred_at)}</span></div><code>{shortValue(event.event_hash)}</code></div></li>)}</ol>
  </section>;
}

function CaseDetail({ detail }: { detail: RecoveryCaseDetail }) {
  const displayStatus = detail.outcome?.status === "payment_link_pending" ? "payment_link_pending" : detail.recovery_case.status;
  const latestProviderStatus = [...detail.actions]
    .sort((left, right) => right.sequence_number - left.sequence_number)
    .find((action) => action.provider_action_status !== null)?.provider_action_status ?? null;
  return <div className="app-shell"><RecoveryNavigation active="case" /><main className="workspace case-workspace">
    <header className="case-header"><div><Link className="back-link" href="/"><ArrowLeft size={16} /> Command center</Link><p className="kicker">Recovery case evidence</p><h1>CASE-{shortValue(detail.recovery_case.recovery_case_id)}</h1><p>Opened {formatTimestamp(detail.recovery_case.opened_at)} IST</p></div><div className="case-header__hero"><span>Amount under control</span><strong>{formatMoney(detail.recovery_case.amount_minor, detail.recovery_case.currency)}</strong><div><Badge value={displayStatus} /><span>{detail.recovery_case.active_payment_link_id === null ? "No active payment link" : `Test Link ${shortValue(detail.recovery_case.active_payment_link_id)}`}</span></div></div></header>
    <section className="case-summary"><div><span>Original payment</span><strong>{titleCase(detail.payment_lifecycle.current_state)}</strong><small>Recovery: {titleCase(displayStatus)}</small></div><div><span>Recovery attempts</span><strong>{detail.recovery_case.recovery_attempt_count}</strong></div><div><span>Actions planned</span><strong>{detail.actions.length}</strong></div><div><span>Audit events</span><strong>{detail.audit_chain.total_event_count}</strong></div></section>
    <CaseEvidenceTabs
      lifecycle={<FailureContext detail={detail} />}
      decision={<div className="case-tab-grid"><DecisionTrace detail={detail} /><PolicyExecution detail={detail} /></div>}
      provider={<ProviderActions detail={detail} />}
      outcome={<div className="case-tab-stack"><OutcomeProof detail={detail} /><AuditTimeline detail={detail} /></div>}
      caseStatus={detail.recovery_case.status}
      outcomeStatus={detail.outcome?.status ?? null}
      providerStatus={latestProviderStatus}
    />
  </main></div>;
}

function CaseUnavailable() {
  return <div className="app-shell"><RecoveryNavigation active="case" /><main className="workspace workspace--unavailable"><section className="unavailable-card"><p className="kicker">Case unavailable</p><h1>This recovery case could not be loaded.</h1><p>It may no longer exist in the local ledger, or the ReclaimRail API may not be running.</p><Link className="refresh-link" href="/">Return to command center</Link></section></main></div>;
}

export default async function RecoveryCasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  const detail = await loadRecoveryCaseDetail(caseId).catch(() => null);
  if (detail === null) return <CaseUnavailable />;
  return <CaseDetail detail={detail} />;
}
