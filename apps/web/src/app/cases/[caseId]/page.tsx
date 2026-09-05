import { ArrowLeft, ArrowUpRight, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { CaseEvidenceTabs } from "@/components/case-evidence-tabs";
import { DashboardLiveRefresh } from "@/components/dashboard-live-refresh";
import { LinkExpiryCountdown } from "@/components/live-time";
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
  if (["blocked", "cancelled", "closed_without_execution", "escalated", "failed", "stopped"].includes(value)) return "danger";
  if (["waiting", "executing", "scheduled", "payment_link_pending"].includes(value)) return "warning";
  if (value === "duplicate_collection_prevented") return "protected";
  return "neutral";
}

function Badge({ value }: { value: string }) {
  return <span className={`badge badge--${badgeTone(value)}`}>{titleCase(value)}</span>;
}

function hasExpired(value: string | null): boolean {
  return value !== null && Number.isFinite(Date.parse(value)) && Date.parse(value) <= Date.now();
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
  const runs = [...detail.agent_runs].sort((left, right) => left.run_number - right.run_number);
  const latestRun = runs.at(-1);
  const trace = latestRun?.ai_trace;
  const evidence = [...new Set([...(trace?.evidence_references ?? []), ...(trace?.evidence_codes ?? [])])];
  const latestApproval = [...detail.approvals].sort((left, right) => right.requested_at.localeCompare(left.requested_at))[0];
  return <DetailCard eyebrow="AI recovery brain" title="Gemini recommendation under control">
    <div className="decision-boundary"><strong>AI recommends.</strong><span>Deterministic policy and authorized humans decide what may execute.</span></div>
    <div className="decision-provider"><span>Planning run {latestRun?.run_number ?? "—"}</span><strong>{latestRun === undefined ? "Awaiting evidence" : trace?.fallback_used ? "Deterministic fallback" : titleCase(latestRun.planner_provider)}</strong></div>
    <p className="decision-summary">{latestRun?.reasoning_summary ?? "No planner reasoning is available for this case."}</p>
    <div className="case-ai-readout"><article><span>What Gemini observed</span><strong>{trace?.root_cause_category ? titleCase(trace.root_cause_category) : "No diagnosis recorded"}</strong></article><article><span>What Gemini proposed</span><strong>{trace?.recommended_action ? titleCase(trace.recommended_action) : "No action proposed"}</strong></article><article><span>Who controls money movement</span><strong>Policy, authorised humans, and Razorpay evidence</strong></article></div>
    {trace?.operator_explanation ? <p className="brain-operator-explanation"><b>Why this recommendation:</b> {trace.operator_explanation}</p> : null}
    {latestRun ? <dl className="brain-facts"><div><dt>Observed diagnosis</dt><dd>{trace?.root_cause_category ? titleCase(trace.root_cause_category) : "Not classified"}</dd></div><div><dt>Recoverability</dt><dd>{trace?.recoverability_assessment ? titleCase(trace.recoverability_assessment) : "Not assessed"}</dd></div><div><dt>AI recommendation</dt><dd>{trace?.recommended_action ? titleCase(trace.recommended_action) : "No action proposed"}</dd></div><div><dt>Evidence citations</dt><dd>{trace?.evidence_references.length ? `${trace.evidence_references.length} persisted reference${trace.evidence_references.length === 1 ? "" : "s"}` : "Not recorded"}</dd></div></dl> : null}
    {trace?.fallback_used ? <p className="brain-fallback"><b>Fallback recorded:</b> {trace.fallback_reason ? titleCase(trace.fallback_reason) : "The model result was not used; deterministic recovery logic produced the proposal."}</p> : null}
    <div className="brain-evidence"><span>Evidence used by the planner</span>{evidence.length === 0 ? <p>No display-safe evidence references were persisted.</p> : <ul>{evidence.map((item) => <li key={item}>{titleCase(item)}</li>)}</ul>}</div>
    {trace?.evidence_citations.length ? <div className="trace-citations">{trace.evidence_citations.map((citation) => <article key={citation.reference}><strong>{citation.label}</strong><span>{citation.observations.join(" · ")}</span></article>)}</div> : null}
    {trace?.reasoning_items.length ? <div className="trace-citations"><b>Evidence-cited decision trace</b>{trace.reasoning_items.map((item, index) => <article key={`${item.interpretation}-${index}`}><strong>{item.interpretation}</strong><span><b>Effect on this plan:</b> {item.action_impact}</span></article>)}</div> : null}
    {trace?.alternatives_considered.length ? <div className="trace-citations"><b>Alternatives evaluated</b>{trace.alternatives_considered.map((item) => <article key={`${item.action_type}-${item.disposition}`}><strong>{titleCase(item.action_type)}</strong><span>{item.reason}</span></article>)}</div> : null}
    {trace?.known_uncertainties.length ? <p className="brain-operator-explanation"><b>Known uncertainty:</b> {trace.known_uncertainties.join(" ")}</p> : null}
    {trace?.evidence_tool_names.length ? <p className="brain-tools"><b>Bounded evidence tools:</b> {trace.evidence_tool_names.map(titleCase).join(" · ")}</p> : null}
    {runs.length > 1 ? <p className="brain-replan"><b>{runs.length} planning runs are recorded.</b> The latest recommendation is shown above; earlier plans remain in the audit chain instead of being overwritten.</p> : null}
    {detail.recovery_case.late_authorization_detected_at ? <p className="brain-replan brain-replan--protected"><b>New provider evidence: late authorization detected.</b> Recovery work must be revalidated and obsolete collection actions may be stopped or cancelled. Check Outcome & audit for the recorded result.</p> : null}
    {latestApproval ? <div className="brain-approval"><span>Human authorization</span><strong>{titleCase(latestApproval.status)}</strong><p><b>Review trigger:</b> {titleCase(latestApproval.request_reason)}.</p>{latestApproval.decision_reason ? <p><b>Recorded decision reason:</b> {latestApproval.decision_reason}</p> : <p>No operator decision has been recorded yet.</p>}{latestApproval.decided_at ? <p><b>Decided:</b> {formatTimestamp(latestApproval.decided_at)}{latestApproval.decided_by ? ` by ${latestApproval.decided_by}` : ""}</p> : null}<p>Approval permits only the reviewed action and never bypasses a hard policy block.</p></div> : null}
    <div className="decision-actions">
      {detail.actions.length === 0 ? <p>No proposed recovery actions.</p> : detail.actions.map((action) => <div className="decision-action" key={action.recovery_action_id}>
        <div><strong>{titleCase(action.action_type)}</strong><span>{action.proposal_reason}</span></div><Badge value={action.policy_outcome} />
      </div>)}
    </div>
  </DetailCard>;
}

function PolicyExecution({ detail }: { detail: RecoveryCaseDetail }) {
  const latestAction = [...detail.actions].sort((left, right) => right.sequence_number - left.sequence_number)[0];
  const policyOutcome = latestAction?.policy_outcome ?? "not_evaluated";
  const policyExplanation = latestAction?.policy_explanation ?? "No deterministic policy decision was persisted.";
  return <DetailCard eyebrow="Deterministic policy" title="Guardrails evaluated before execution">
    <div className="policy-status"><span className={`policy-status__dot policy-status__dot--${badgeTone(policyOutcome)}`} /><div><strong>{titleCase(policyOutcome)}</strong><p>{policyExplanation}</p></div></div>
    {latestAction ? <p className="policy-provenance"><b>Recorded policy revision:</b> {latestAction.policy_version} · evaluated {formatTimestamp(latestAction.policy_evaluated_at)}. Each rule below is the exact persisted rule and observed value used for this action.</p> : null}
    {latestAction?.policy_check_results.length ? <div className="policy-check-list">{latestAction.policy_check_results.map((check) => <article key={check.code}><header><strong>{check.label}</strong><Badge value={check.result} /></header><p><b>Observed:</b> {check.actual_value}</p><small><b>Rule:</b> {check.rule}</small></article>)}</div> : <p className="detail-empty">This older action predates persisted per-check policy evidence.</p>}
  </DetailCard>;
}

function ProviderActions({ detail }: { detail: RecoveryCaseDetail }) {
  const latestApproval = [...detail.approvals].sort((left, right) => right.requested_at.localeCompare(left.requested_at))[0];
  const planClosed = latestApproval?.status === "rejected" || latestApproval?.status === "expired";
  return <DetailCard eyebrow="Provider execution" title="Bounded Razorpay actions">
    <div className="action-list">{detail.actions.length === 0 ? <p>No recovery actions were persisted.</p> : detail.actions.map((action) => {
      const expired = hasExpired(action.provider_action_expires_at);
      const neverExecuted = action.execution_attempt_count === 0 && action.provider_action_id === null && action.started_at === null;
      const displayStatus = planClosed && neverExecuted ? "not_executed" : neverExecuted && action.status === "allowed" ? "allowed_by_policy" : action.status;
      return <article className="provider-action" key={action.recovery_action_id}>
      <div className="provider-action__heading"><div><strong>{action.sequence_number}. {titleCase(action.action_type)}</strong><span>{neverExecuted ? planClosed ? `Not executed · protected review ${latestApproval.status}` : "Policy permitted · no execution attempt" : `${action.execution_attempt_count} execution attempt${action.execution_attempt_count === 1 ? "" : "s"}`}</span></div><Badge value={displayStatus} /></div>
      <dl><div><dt>Provider reference</dt><dd className="mono-value">{action.provider_action_id ?? "Not created"}</dd></div><div><dt>Provider status</dt><dd>{action.provider_action_status === null ? "Not available" : titleCase(action.provider_action_status)}</dd></div><div><dt>Expires</dt><dd>{action.provider_action_expires_at === null ? "Provider managed" : <><span>Expires on {formatTimestamp(action.provider_action_expires_at)} IST</span>{!expired && action.provider_action_status !== "paid" ? <small className="provider-action__expiry"><LinkExpiryCountdown expiresAt={action.provider_action_expires_at} /> · Razorpay payment confirmation decides the final outcome.</small> : null}</>}</dd></div><div><dt>Recovery link</dt><dd>{action.provider_action_status === "paid" ? "Paid — recovery complete" : expired ? "Expired — ReclaimRail will not offer payment access" : action.provider_action_url === null ? "Not created" : <a className="provider-action__link" href={action.provider_action_url} target="_blank" rel="noreferrer noopener">Open hosted Razorpay Test Link <ArrowUpRight size={16} /></a>}</dd></div>{action.last_error ? <div><dt>Provider failure</dt><dd className="mono-value">{action.last_error}</dd></div> : null}</dl>
    </article>})}</div>
  </DetailCard>;
}

function OutcomeProof({ detail }: { detail: RecoveryCaseDetail }) {
  const outcome = detail.outcome;
  const latestApproval = [...detail.approvals].sort((left, right) => right.requested_at.localeCompare(left.requested_at))[0];
  const providerAction = detail.actions.find((action) => action.provider_action_id !== null || action.started_at !== null);
  if (outcome === null && latestApproval?.status === "pending") return <DetailCard eyebrow="Outcome proof" title="Awaiting protected human decision"><p className="detail-empty">A real approval record is pending. No provider action has executed, so there is no Razorpay outcome to await yet.</p></DetailCard>;
  if (outcome === null && latestApproval?.status === "rejected") return <DetailCard eyebrow="Outcome proof" title="Reviewed action declined before execution"><p className="detail-empty">The protected reviewer declined the reviewed action. No payment link or customer message was executed, no Razorpay outcome is expected, and this recovery attempt is closed.</p></DetailCard>;
  if (outcome === null && latestApproval?.status === "expired") return <DetailCard eyebrow="Outcome proof" title="Approval expired before execution"><p className="detail-empty">The protected approval window ended before execution. No provider action ran, no provider outcome is expected, and this recovery attempt is closed safely.</p></DetailCard>;
  if (outcome === null && providerAction === undefined) return <DetailCard eyebrow="Outcome proof" title="No provider outcome expected yet"><p className="detail-empty">This case has no recorded provider execution. {detail.recovery_case.status === "escalated" ? "The historical escalation also has no active approval record; it is not in the Human Review queue." : "A provider outcome will appear only after an allowed action executes."}</p></DetailCard>;
  if (outcome === null) return <DetailCard eyebrow="Outcome proof" title="Awaiting payment confirmation"><p className="detail-empty">A provider action was recorded, but Razorpay has not confirmed a recovery payment yet.</p></DetailCard>;
  const recovered = outcome.gross_recovered_minor - outcome.reversed_minor;
  const isRecovered = recovered > 0;
  const duplicatePrevented = outcome.status === "duplicate_collection_prevented";
  const pending = outcome.status === "payment_link_pending";
  const expired = outcome.status === "payment_link_expired";
  const cancelled = outcome.status === "payment_link_cancelled";
  const lateAuthorizationStop = detail.recovery_case.late_authorization_detected_at !== null && (cancelled || duplicatePrevented);
  const amount = isRecovered ? recovered : duplicatePrevented ? outcome.duplicate_collection_prevented_minor : 0;
  const title = pending
    ? "Awaiting recovery-link payment"
    : lateAuthorizationStop
      ? "Unsafe duplicate recovery stopped"
      : expired
        ? "Recovery link expired safely"
        : cancelled
          ? "Recovery link cancelled safely"
          : "Verified recovery result";
  const amountClass = isRecovered ? "outcome-proof__money outcome-proof__money--recovered" : duplicatePrevented ? "outcome-proof__money outcome-proof__money--protected" : "outcome-proof__money";
  const amountLabel = isRecovered ? "Verified recovered" : duplicatePrevented ? "Duplicate collection prevented" : expired || cancelled ? "Recovered so far" : "Recovered so far";
  const safetyExplanation = lateAuthorizationStop
    ? "Original payment authorization arrived after the failure. ReclaimRail stopped the obsolete recovery action and preserved the provider evidence to prevent duplicate collection."
    : expired
      ? "The provider-confirmed recovery window ended. The link is no longer actionable and no recovered revenue was recorded."
      : cancelled
        ? "The provider-confirmed recovery link was cancelled. No recovered revenue was recorded."
        : null;
  return <DetailCard eyebrow="Outcome proof" title={title}>
    <div className="outcome-proof"><Badge value={outcome.status} /><strong className={amountClass}>{formatMoney(amount, detail.recovery_case.currency)}</strong><span>{amountLabel}</span>{pending ? <p className="outcome-proof__waiting">The Test Payment Link exists, but Razorpay has not confirmed a recovery payment.</p> : null}{safetyExplanation ? <p className="outcome-proof__waiting">{safetyExplanation}</p> : null}</div>
    <dl className="outcome-facts"><div><dt>Attribution</dt><dd>{titleCase(outcome.attribution)}</dd></div><div><dt>Evidence</dt><dd>{outcome.evidence_event_count} linked events</dd></div><div><dt>Occurred</dt><dd>{formatTimestamp(outcome.occurred_at)}</dd></div></dl>
  </DetailCard>;
}

function AuditTimeline({ detail }: { detail: RecoveryCaseDetail }) {
  function eventLabel(event: RecoveryCaseDetail["audit_chain"]["events"][number]): string {
    if (event.event_type !== "outcome.payment_link.reconciled") return titleCase(event.event_type);
    const providerStatus = event.provider_status;
    if (providerStatus === "paid") return "Recovery payment confirmed";
    if (providerStatus === "created") return "Payment link observed — awaiting payment";
    if (typeof providerStatus === "string") return `Payment link observed — ${titleCase(providerStatus)}`;
    return "Payment link status recorded";
  }
  return <section className="audit-timeline"><div className="audit-timeline__heading"><div className="audit-timeline__title"><span><ShieldCheck size={22} /></span><div><p className="kicker">Tamper-evident audit chain</p><h2>Decision and outcome evidence</h2></div></div><Badge value={detail.audit_chain.valid ? "succeeded" : "failed"} /></div>
    <p className="audit-timeline__intro">{detail.audit_chain.valid ? `${detail.audit_chain.checked_event_count} linked events verified with ${detail.audit_chain.events[0]?.hash_algorithm ?? "the configured"} hash chain.` : detail.audit_chain.reason}</p>
    <ol>{detail.audit_chain.events.map((event) => <li key={event.sequence_number}><span className="timeline-marker" /><div className="timeline-event"><div><strong>{eventLabel(event)}</strong><span>{titleCase(event.actor_type)} · {formatTimestamp(event.occurred_at)}</span></div><code>{shortValue(event.event_hash)}</code></div></li>)}</ol>
  </section>;
}

function CaseDetail({ detail }: { detail: RecoveryCaseDetail }) {
  const latestApproval = [...detail.approvals].sort((left, right) => right.requested_at.localeCompare(left.requested_at))[0];
  const displayStatus = detail.outcome?.status === "payment_link_pending"
    ? "payment_link_pending"
    : ["rejected", "expired"].includes(latestApproval?.status ?? "")
      ? "closed_without_execution"
      : detail.recovery_case.status;
  const latestProviderStatus = [...detail.actions]
    .sort((left, right) => right.sequence_number - left.sequence_number)
    .find((action) => action.provider_action_status !== null)?.provider_action_status ?? null;
  return <div className="app-shell"><RecoveryNavigation active="case" /><DashboardLiveRefresh /><main className="workspace case-workspace">
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
