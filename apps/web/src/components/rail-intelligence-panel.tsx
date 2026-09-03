import { AlertTriangle, ShieldCheck, TrendingDown } from "lucide-react";

import { type RecoveryIncident } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, titleCase } from "@/lib/presentation";

function impactFor(incident: RecoveryIncident): string {
  if (["critical", "high"].includes(incident.severity)) return "High-severity rail degradation can stop or escalate money-facing recovery until policy permits a safe action.";
  return "This signal is included in deterministic policy evaluation before a recovery action is allowed.";
}

export function RailIntelligencePanel({ incidents, currency }: { incidents: RecoveryIncident[]; currency: string }) {
  if (incidents.length === 0) return <div className="rail-calm"><ShieldCheck size={28} /><div><strong>No active payment-rail incidents</strong><p>ReclaimRail does not invent degradation. Recovery policy is currently evaluating each case against normal rail conditions.</p></div></div>;
  return <div className="rail-intelligence">{incidents.map((incident) => { const baseline = Math.round(incident.baseline_failure_rate * 100); const current = Math.round(incident.failure_rate * 100); return <article className="rail-card" key={incident.incident_id}><div className="rail-card__heading"><div><p className="kicker">{titleCase(incident.severity)} severity · {titleCase(incident.scope)}</p><h3>{titleCase(incident.dimension_value)} payment degradation</h3></div><span className="badge badge--danger">{titleCase(incident.status)}</span></div><div className="rail-card__metrics"><div><span>Baseline failure rate</span><strong>{baseline}%</strong></div><div><span>Current failure rate</span><strong>{current}%</strong></div><div><span>Revenue at risk</span><strong>{formatMoney(incident.revenue_at_risk_minor, currency)}</strong></div><div><span>Signal confidence</span><strong>{Math.round(incident.confidence * 100)}%</strong></div></div><div className="rail-rate"><span>Failure-rate movement</span><div><i style={{ width: `${Math.min(100, Math.max(4, baseline))}%` }} /><b style={{ width: `${Math.min(100, Math.max(4, current))}%` }} /></div><small>Baseline <TrendingDown size={13} /> Current</small></div><div className="rail-card__impact"><AlertTriangle size={18} /><div><strong>Recovery impact</strong><p>{impactFor(incident)}</p></div></div><footer>{incident.occurrence_count} observations · last seen {formatTimestamp(incident.last_detected_at)}</footer></article>; })}</div>;
}
