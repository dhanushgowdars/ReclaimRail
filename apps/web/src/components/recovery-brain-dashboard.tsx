import {
  ArrowRight,
  Bot,
  CircleAlert,
  CircleStop,
  Eye,
  FileCheck2,
  Route,
  ShieldCheck,
  UserRoundCheck,
} from "lucide-react";
import Link from "next/link";

import { DashboardLiveRefresh } from "@/components/dashboard-live-refresh";
import { RailIntelligencePanel } from "@/components/rail-intelligence-panel";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import {
  type RecoveryCaseDetail,
  type RecoveryCaseQueueItem,
  type RecoveryIncident,
} from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

function label(value: string | null | undefined, fallback = "Not recorded"): string {
  return value ? titleCase(value) : fallback;
}

function statusTone(value: string | null | undefined): string {
  if (["allow", "recovered", "succeeded", "approved", "paid"].includes(value ?? "")) return "success";
  if (["block", "blocked", "stopped", "cancelled", "failed"].includes(value ?? "")) return "danger";
  if (["escalate", "escalated", "pending"].includes(value ?? "")) return "protected";
  return "warning";
}

function verdictMeaning(value: string | null | undefined): { title: string; detail: string } {
  if (value === "allow") return { title: "Allow means eligible—not recovered", detail: "All applicable deterministic checks passed. The worker may execute only the persisted action; Razorpay must still confirm payment before revenue is recorded." };
  if (value === "escalate") return { title: "Escalate means pause for accountable review", detail: "The action is otherwise eligible but crosses a protected boundary. A reviewer may approve or reject only this recorded action and cannot override a failed hard rule." };
  if (value === "block") return { title: "Block means execution is prohibited", detail: "At least one hard safety rule failed. Neither Gemini nor a human approval can release the provider action while that evidence remains unsafe." };
  return { title: "No executable verdict yet", detail: "Provider evidence, a persisted plan, and deterministic evaluation must exist before any recovery action can execute." };
}

function TraceStep({
  number,
  label: stepLabel,
  detail,
  state,
}: {
  number: number;
  label: string;
  detail: string;
  state: "done" | "active" | "waiting";
}) {
  return <article className={`brain-trace__step brain-trace__step--${state}`}>
    <span>{number}</span>
    <div><strong>{stepLabel}</strong><small>{detail}</small></div>
  </article>;
}

function DecisionEvidenceTrace({
  trace,
}: {
  trace: RecoveryCaseDetail["agent_runs"][number]["ai_trace"] | undefined;
}) {
  if (!trace) return null;

  return <>
    {trace.reasoning_items.length > 0 ? <section className="brain-decision-trace">
      <strong>Evidence-cited decision trace</strong>
      {trace.reasoning_items.map((item, index) => <article key={`${item.interpretation}-${index}`}>
        <p>{item.interpretation}</p>
        <small><b>Effect on this plan:</b> {item.action_impact}</small>
      </article>)}
    </section> : null}
    {trace.alternatives_considered.length > 0 ? <section className="brain-alternatives">
      <strong>Alternatives evaluated</strong>
      {trace.alternatives_considered.map((alternative) => <p key={`${alternative.action_type}-${alternative.disposition}`}>
        <b>{label(alternative.action_type)}:</b> {alternative.reason}
      </p>)}
    </section> : null}
    {trace.known_uncertainties.length > 0 ? <p className="brain-uncertainty"><b>Known uncertainty:</b> {trace.known_uncertainties.join(" ")}</p> : null}
  </>;
}

function ProviderProgress({ detail }: { detail: RecoveryCaseDetail }) {
  const outcome = detail.outcome;
  const pending = outcome?.status === "payment_link_pending";
  const recovered = outcome ? outcome.gross_recovered_minor - outcome.reversed_minor : 0;
  const title = pending ? "Payment link created — awaiting payment" : outcome ? label(outcome.status) : "Awaiting Razorpay payment confirmation";
  const description = pending
    ? "Razorpay created the recovery link. This is provider progress, not an outcome and not revenue. The case changes only when Razorpay records payment, expiry, or cancellation."
    : outcome
      ? `${formatMoney(recovered, detail.recovery_case.currency)} is counted only after Razorpay confirms payment and linked evidence is recorded.`
      : "No revenue is counted until Razorpay confirms the recovery payment in the Outcome Ledger.";
  return <section className="brain-outcome"><FileCheck2 size={25} /><div><p className="kicker">{pending ? "Provider progress" : "Provider outcome proof"}</p><h2>{title}</h2><p>{description}</p></div><Link href="/outcomes">Open Outcome Ledger <ArrowRight size={16} /></Link></section>;
}

export function RecoveryBrainDashboard({
  detail,
  cases,
  incidents,
}: {
  detail: RecoveryCaseDetail | null;
  cases: RecoveryCaseQueueItem[];
  incidents: RecoveryIncident[];
}) {
  const latestRun = detail ? [...detail.agent_runs].sort((a, b) => b.run_number - a.run_number)[0] : undefined;
  const trace = latestRun?.ai_trace;
  const latestAction = detail ? [...detail.actions].sort((a, b) => b.sequence_number - a.sequence_number)[0] : undefined;
  const approval = detail ? [...detail.approvals].sort((a, b) => b.requested_at.localeCompare(a.requested_at))[0] : undefined;
  const outcome = detail?.outcome;
  const evidence = detail ? [
    `Payment state: ${label(detail.payment_lifecycle.current_state)}`,
    `Payment method: ${label(detail.payment_lifecycle.payment_method, "Unknown")}`,
    `Failure: ${label(detail.payment_lifecycle.error_reason ?? detail.payment_lifecycle.error_code, "Provider failure")}`,
    `Attempts: ${detail.recovery_case.recovery_attempt_count}`,
    `Rail incident: ${detail.recovery_case.source_incident_id ? "linked" : "none active for this case"}`,
  ] : [];
  const hasProviderAction = Boolean(latestAction?.provider_action_id || latestAction?.completed_at);
  const hasReplan = Boolean(detail && (detail.agent_runs.length > 1 || detail.recovery_case.late_authorization_detected_at));
  const verdict = verdictMeaning(latestAction?.policy_outcome);

  return <div className="app-shell"><RecoveryNavigation active="intelligence" /><DashboardLiveRefresh />
    <main className="workspace recovery-brain">
      <header className="recovery-brain__hero">
        <div><p className="kicker">Recovery decision center</p><h1>Recovery Brain</h1><p>Inspect the recorded recommendation behind a real case. Gemini may propose; deterministic policy and authorised humans control execution; Razorpay evidence proves the result.</p></div>
        <section className="recovery-brain__boundary"><Bot size={22} /><div><strong>Recommendation is not authority</strong><span>No payment action moves from this page without a persisted policy verdict and any required approval.</span></div></section>
      </header>

      {detail === null ? <section className="brain-empty"><CircleAlert size={24} /><div><strong>No recovery case is available yet</strong><p>Start and fail a Razorpay Test Mode payment to create provider-backed evidence. The Brain does not invent a recommendation without a case.</p><Link href="/payment-lab">Start live Test Mode run <ArrowRight size={16} /></Link></div></section> : <>
        <section className="brain-case-strip" aria-label="Selected case">
          <div><p className="kicker">Selected persisted case</p><strong>CASE-{shortId(detail.recovery_case.recovery_case_id)}</strong><span>Opened {formatTimestamp(detail.recovery_case.opened_at)}</span></div>
          <div><span>Amount under control</span><strong>{formatMoney(detail.recovery_case.amount_minor, detail.recovery_case.currency)}</strong></div>
          <Link href={`/cases/${detail.recovery_case.recovery_case_id}`}>Open full case evidence <ArrowRight size={16} /></Link>
        </section>

        <section className="brain-grid">
          <article className="brain-card brain-card--evidence"><div className="brain-card__heading"><div><p className="kicker">1. Observed evidence</p><h2>What reached the server</h2></div><Eye size={22} /></div><div className="brain-evidence-list">{evidence.map((item) => <span key={item}>{item}</span>)}</div><p>These fields are persisted payment and incident context—not a model guess.</p></article>

          <article className="brain-card brain-card--recommendation"><div className="brain-card__heading"><div><p className="kicker">2. AI diagnosis & proposal</p><h2>{label(trace?.recommended_action, "No action proposed")}</h2></div><span className={`badge badge--${trace?.fallback_used ? "warning" : "protected"}`}>{trace?.fallback_used ? "Deterministic fallback" : latestRun ? label(latestRun.planner_provider) : "Awaiting trace"}</span></div><p className="brain-card__summary">{latestRun?.reasoning_summary ?? "A planner run has not been recorded for this case."}</p>{trace?.operator_explanation ? <div className="brain-why"><strong>Why this recommendation</strong><p>{trace.operator_explanation}</p></div> : null}<dl className="brain-diagnosis"><div><dt>Diagnosis</dt><dd>{label(trace?.root_cause_category, "Not classified")}</dd></div><div><dt>Recoverability</dt><dd>{label(trace?.recoverability_assessment, "Not assessed")}</dd></div><div><dt>Evidence citations</dt><dd>{trace?.evidence_references.length ?? 0}</dd></div><div><dt>Planning run</dt><dd>{latestRun?.run_number ?? "—"}</dd></div></dl>{trace?.evidence_citations.length ? <div className="brain-trace-citations">{trace.evidence_citations.map((citation) => <div key={citation.reference}><strong>{citation.label}</strong><span>{citation.observations.join(" · ")}</span></div>)}</div> : null}<DecisionEvidenceTrace trace={trace} />{trace?.fallback_used ? <p className="brain-fallback"><b>Fallback reason:</b> {label(trace.fallback_reason, "Model output was not used")}</p> : null}</article>

          <article className="brain-card brain-card--policy"><div className="brain-card__heading"><div><p className="kicker">3. Deterministic policy verdict</p><h2>{label(latestAction?.policy_outcome, "Not evaluated")}</h2></div><ShieldCheck size={22} /></div><div className={`brain-verdict brain-verdict--${latestAction?.policy_outcome ?? "pending"}`}><strong>{verdict.title}</strong><p>{verdict.detail}</p></div><p className="brain-card__summary">{latestAction?.policy_explanation ?? "No policy decision is persisted yet."}</p><div className="brain-policy-result"><span className={`badge badge--${statusTone(latestAction?.policy_outcome)}`}>{label(latestAction?.policy_outcome, "Pending")}</span><strong>{latestAction ? `Permitted action: ${label(latestAction.action_type)}` : "No action may execute"}</strong></div>{latestAction?.policy_check_results.length ? <div className="brain-policy-checks">{latestAction.policy_check_results.map((check) => <div key={check.code}><span className={`badge badge--${check.result === "passed" ? "success" : check.result === "requires_review" ? "warning" : check.result === "failed" ? "danger" : "neutral"}`}>{label(check.result)}</span><strong>{check.label}</strong><small><b>Observed value:</b> {check.actual_value}</small></div>)}</div> : <p>Detailed check evidence will appear for newly planned actions.</p>}</article>

          <article className="brain-card brain-card--boundary"><div className="brain-card__heading"><div><p className="kicker">4. Human boundary</p><h2>{approval ? label(approval.status) : "No review required"}</h2></div><UserRoundCheck size={22} /></div><p className="brain-card__summary">{approval ? `${label(approval.request_reason)}. This approval covers only the reviewed action and cannot override a policy block.` : "The recorded policy did not require protected human review for this action."}</p>{approval ? <p className="brain-meta">Requested {formatTimestamp(approval.requested_at)} · expires {formatTimestamp(approval.expires_at)}</p> : <p className="brain-meta">High-value or escalated actions appear in the Human reviews queue.</p>}<Link href="/reviews">Open Human reviews <ArrowRight size={16} /></Link></article>
        </section>

        <section className="brain-card brain-card--wide"><div className="brain-card__heading"><div><p className="kicker">Recorded decision pathway</p><h2>Observe → Diagnose → Plan → Gate → Act → Verify → Re-plan / stop</h2></div><Route size={23} /></div><div className="brain-trace">
          <TraceStep number={1} label="Observe" detail="Provider payment state and failure were persisted." state="done" />
          <TraceStep number={2} label="Diagnose" detail={latestRun ? `${label(trace?.root_cause_category, "Diagnosis") } recorded by planner.` : "Waiting for a planner run."} state={latestRun ? "done" : "waiting"} />
          <TraceStep number={3} label="Plan" detail={latestRun ? `${latestRun.proposed_action_count} proposed action${latestRun.proposed_action_count === 1 ? "" : "s"} persisted.` : "No bounded plan yet."} state={latestRun ? "done" : "waiting"} />
          <TraceStep number={4} label="Safety gate" detail={latestAction ? `Policy ${label(latestAction.policy_outcome).toLowerCase()} recorded.` : "Waiting for deterministic policy."} state={latestAction ? "done" : "waiting"} />
          <TraceStep number={5} label="Act" detail={hasProviderAction ? "Provider action record exists." : "No provider action has been recorded."} state={hasProviderAction ? "done" : "waiting"} />
          <TraceStep number={6} label="Verify" detail={outcome ? `Outcome: ${label(outcome.status)}.` : "Waiting for Razorpay payment confirmation."} state={outcome ? "done" : "waiting"} />
          <TraceStep number={7} label="Re-plan / stop" detail={hasReplan ? detail?.recovery_case.late_authorization_detected_at ? "Late authorization was recorded; recovery was revalidated." : "A later planning run is present in audit evidence." : "No new evidence requiring re-plan is recorded."} state={hasReplan ? "active" : "waiting"} />
        </div></section>

        <section className="brain-candidate-section"><div><p className="kicker">Candidate action boundaries</p><h2>What the recorded plan did—and did not—propose</h2><p>Only the chosen recommendation is an AI decision. The other rows are safety paths, not invented rejected recommendations.</p></div><div className="brain-candidates">{[
          ["Wait", "Not recorded in this plan", "Monitoring continues until new provider evidence changes the case."],
          ["Create payment link", latestAction?.action_type === "create_payment_link" ? `Proposed · policy ${label(latestAction.policy_outcome).toLowerCase()}` : "Not recorded in this plan", "Creates only a bounded link for the original amount when policy allows."],
          ["Escalate", approval || latestAction?.policy_outcome === "escalate" ? "Escalation path recorded" : "Not recorded in this plan", "Protected human review is required when the policy threshold or risk requires it."],
          ["Stop recovery", detail.recovery_case.late_authorization_detected_at || detail.payment_lifecycle.recovery_stopped_at ? "Stop condition recorded" : "No stop condition recorded", "Late authorization or a hard guardrail stops unsafe recovery work."],
        ].map(([name, state, explanation]) => <article key={name}><div><strong>{name}</strong><span>{explanation}</span></div><em className={state.includes("Proposed") || state.includes("recorded") ? "is-recorded" : ""}>{state}</em></article>)}</div></section>

        <ProviderProgress detail={detail} />
      </>}

      <section className="brain-case-list"><div className="brain-card__heading"><div><p className="kicker">Other persisted cases</p><h2>Inspect another decision</h2></div><Link href="/cases">All cases <ArrowRight size={16} /></Link></div>{cases.length === 0 ? <p>No cases yet.</p> : <div>{cases.slice(0, 8).map((item) => <Link href={`/cases/${item.recovery_case_id}`} key={item.recovery_case_id}><span>CASE-{shortId(item.recovery_case_id)}</span><strong>{label(item.latest_action_type, "Awaiting plan")}</strong><em className={`badge badge--${statusTone(item.outcome_status ?? item.latest_action_policy_outcome ?? item.status)}`}>{label(item.outcome_status ?? item.latest_action_policy_outcome ?? item.status)}</em><ArrowRight size={16} /></Link>)}</div>}</section>

      <section className="brain-rail"><div className="brain-card__heading"><div><p className="kicker">Payment-rail context</p><h2>Live signals that can constrain recovery</h2></div><CircleStop size={22} /></div><RailIntelligencePanel incidents={incidents} currency={detail?.recovery_case.currency ?? "INR"} /></section>
    </main>
  </div>;
}
