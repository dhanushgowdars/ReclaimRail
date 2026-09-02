import { CheckCircle2, CirclePause, ShieldAlert, ShieldCheck } from "lucide-react";

import { type RecoveryCaseQueueItem, type RecoveryDashboardSummary } from "@/lib/recovery-api";
import { titleCase } from "@/lib/presentation";

const controls = [
  ["Consent and quiet hours", "Contact actions are deferred unless the recipient and timing satisfy policy."],
  ["High-value approval", "Money-facing actions over the protected threshold wait for an operator decision."],
  ["Idempotent execution", "The same recovery action cannot create duplicate payment links or duplicate collection."],
  ["Late authorization stop", "A late payment authorization stops unsafe recovery and preserves the evidence."],
  ["Provider-confirmed accounting", "Recovered revenue changes only after Razorpay reconciliation and linked evidence."],
] as const;

export function SafetyControlsPanel({ summary, cases }: { summary: RecoveryDashboardSummary; cases: RecoveryCaseQueueItem[] }) {
  const escalated = cases.filter((item) => item.latest_action_policy_outcome === "escalate" || item.status === "escalated").length;
  const blocked = cases.filter((item) => item.latest_action_policy_outcome === "block" || item.status === "blocked").length;
  const lateAuthorization = cases.filter((item) => item.late_authorization_detected_at !== null).length;
  return <div className="safety-panel"><section className="safety-panel__state"><div><p className="kicker">Current evidence-backed state</p><h2>Controls remain active</h2><p>These values are derived from the visible recovery-case data. {summary.open_incident_count} active rail incident{summary.open_incident_count === 1 ? " is" : "s are"} currently included in policy evaluation.</p></div><ShieldCheck size={34} /></section><div className="safety-panel__counters"><article><ShieldAlert size={19} /><span>Escalated cases</span><strong>{escalated}</strong><small>Awaiting or requiring human control</small></article><article><CirclePause size={19} /><span>Blocked cases</span><strong>{blocked}</strong><small>Policy did not allow execution</small></article><article><CheckCircle2 size={19} /><span>Late-authorization stops</span><strong>{lateAuthorization}</strong><small>Unsafe recovery prevented</small></article></div><section className="safety-panel__rules"><div className="panel-heading"><div><p className="kicker">Guardrail contract</p><h2>What ReclaimRail enforces</h2></div></div>{controls.map(([name, detail]) => <article key={name}><CheckCircle2 size={18} /><div><strong>{name}</strong><p>{detail}</p></div><span>Enforced</span></article>)}</section><p className="safety-panel__footnote">Policy outcomes such as {titleCase("allow")}, {titleCase("block")}, or {titleCase("escalate")} are persisted on individual recovery actions and can be inspected from the linked case evidence.</p></div>;
}
