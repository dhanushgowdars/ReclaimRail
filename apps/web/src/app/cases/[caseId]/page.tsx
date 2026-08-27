import Link from "next/link";

import { RecoveryNavigation } from "@/components/recovery-navigation";
import {
  type RecoveryCaseDetail,
  loadRecoveryCaseDetail,
} from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

function formatMoney(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

function formatTimestamp(timestamp: string | null): string {
  if (timestamp === null) return "Not available";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

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
  const uniqueGuardrails = [...new Set(detail.actions.flatMap((action) => action.policy_guardrails))];
  return <DetailCard eyebrow="Deterministic policy" title="Guardrails evaluated before execution">
    <div className="policy-status"><span className={`policy-status__dot policy-status__dot--${badgeTone(detail.recovery_case.status)}`} /><div><strong>{titleCase(detail.recovery_case.status)}</strong><p>{detail.recovery_case.close_reason === null ? "The current case state is controlled by lifecycle and policy rules." : titleCase(detail.recovery_case.close_reason)}</p></div></div>
    <ul className="guardrail-list">{uniqueGuardrails.length === 0 ? <li>No guardrail codes were persisted.</li> : uniqueGuardrails.map((guardrail) => <li key={guardrail}>{titleCase(guardrail)}</li>)}</ul>
  </DetailCard>;
}

function ProviderActions({ detail }: { detail: RecoveryCaseDetail }) {
  return <DetailCard eyebrow="Provider execution" title="Bounded Razorpay actions">
    <div className="action-list">{detail.actions.length === 0 ? <p>No recovery actions were persisted.</p> : detail.actions.map((action) => <article className="provider-action" key={action.recovery_action_id}>
      <div className="provider-action__heading"><div><strong>{action.sequence_number}. {titleCase(action.action_type)}</strong><span>{action.execution_attempt_count} execution attempt{action.execution_attempt_count === 1 ? "" : "s"}</span></div><Badge value={action.status} /></div>
      <dl><div><dt>Provider reference</dt><dd className="mono-value">{action.provider_action_id ?? "Not created"}</dd></div><div><dt>Provider status</dt><dd>{action.provider_action_status === null ? "Not available" : titleCase(action.provider_action_status)}</dd></div><div><dt>Expires</dt><dd>{action.provider_action_expires_at === null ? "Provider managed" : formatTimestamp(action.provider_action_expires_at)}</dd></div><div><dt>Recovery link</dt><dd>{action.provider_action_url === null ? "Not created" : <a className="provider-action__link" href={action.provider_action_url} target="_blank" rel="noreferrer noopener">Open Razorpay link</a>}</dd></div></dl>
    </article>)}</div>
  </DetailCard>;
}

function OutcomeProof({ detail }: { detail: RecoveryCaseDetail }) {
  const outcome = detail.outcome;
  if (outcome === null) return <DetailCard eyebrow="Outcome proof" title="Awaiting provider evidence"><p className="detail-empty">No verified recovery outcome has been reconciled for this case yet.</p></DetailCard>;
  const recovered = outcome.gross_recovered_minor - outcome.reversed_minor;
  const isRecovered = recovered > 0;
  const amount = isRecovered ? recovered : outcome.duplicate_collection_prevented_minor;
  return <DetailCard eyebrow="Outcome proof" title="Verified reconciliation result">
    <div className="outcome-proof"><Badge value={outcome.status} /><strong className={isRecovered ? "outcome-proof__money outcome-proof__money--recovered" : "outcome-proof__money outcome-proof__money--protected"}>{formatMoney(amount, detail.recovery_case.currency)}</strong><span>{isRecovered ? "Verified recovered" : "Duplicate collection prevented"}</span></div>
    <dl className="outcome-facts"><div><dt>Attribution</dt><dd>{titleCase(outcome.attribution)}</dd></div><div><dt>Evidence</dt><dd>{outcome.evidence_event_count} linked events</dd></div><div><dt>Occurred</dt><dd>{formatTimestamp(outcome.occurred_at)}</dd></div></dl>
  </DetailCard>;
}

function AuditTimeline({ detail }: { detail: RecoveryCaseDetail }) {
  return <section className="audit-timeline"><div className="audit-timeline__heading"><div><p className="kicker">Tamper-evident audit chain</p><h2>Decision and outcome evidence</h2></div><Badge value={detail.audit_chain.valid ? "succeeded" : "failed"} /></div>
    <p className="audit-timeline__intro">{detail.audit_chain.valid ? `${detail.audit_chain.checked_event_count} linked events verified with ${detail.audit_chain.events[0]?.hash_algorithm ?? "the configured"} hash chain.` : detail.audit_chain.reason}</p>
    <ol>{detail.audit_chain.events.map((event) => <li key={event.sequence_number}><span className="timeline-marker" /><div className="timeline-event"><div><strong>{titleCase(event.event_type)}</strong><span>{titleCase(event.actor_type)} · {formatTimestamp(event.occurred_at)}</span></div><code>{shortValue(event.event_hash)}</code></div></li>)}</ol>
  </section>;
}

function CaseDetail({ detail }: { detail: RecoveryCaseDetail }) {
  return <div className="app-shell"><RecoveryNavigation active="case" /><main className="workspace case-workspace">
    <header className="case-header"><div><Link className="back-link" href="/">← Command center</Link><p className="kicker">Recovery case</p><h1>CASE-{shortValue(detail.recovery_case.recovery_case_id)}</h1><p>Opened {formatTimestamp(detail.recovery_case.opened_at)} · {formatMoney(detail.recovery_case.amount_minor, detail.recovery_case.currency)}</p></div><div className="case-header__status"><Badge value={detail.recovery_case.status} /><span>{detail.recovery_case.active_payment_link_id === null ? "No active payment link" : `Link ${shortValue(detail.recovery_case.active_payment_link_id)}`}</span></div></header>
    <section className="case-summary"><div><span>Payment lifecycle</span><strong>{titleCase(detail.payment_lifecycle.current_state)}</strong></div><div><span>Recovery attempts</span><strong>{detail.recovery_case.recovery_attempt_count}</strong></div><div><span>Actions planned</span><strong>{detail.actions.length}</strong></div><div><span>Audit events</span><strong>{detail.audit_chain.total_event_count}</strong></div></section>
    <section className="case-grid"><FailureContext detail={detail} /><DecisionTrace detail={detail} /><PolicyExecution detail={detail} /><ProviderActions detail={detail} /><OutcomeProof detail={detail} /></section>
    <AuditTimeline detail={detail} />
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
