import { AlertTriangle, ShieldCheck, TrendingDown } from "lucide-react";

import { type RecoveryIncident } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, titleCase } from "@/lib/presentation";

function impactFor(incident: RecoveryIncident): string {
  if (["critical", "high"].includes(incident.severity)) return "The incident circuit breaker blocks automated money-facing recovery for this rail until new provider evidence changes the incident state.";
  return "This recorded signal is included in deterministic policy evaluation before a recovery action is allowed.";
}

function reasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    failure_rate_threshold: "Failure rate crossed the configured floor",
    baseline_uplift: "Failure rate increased above the stored baseline",
    robust_deviation: "The robust deviation threshold was exceeded",
    rate_multiplier: "Failure rate exceeded the configured baseline multiplier",
    revenue_at_risk: "Provider failures created recorded revenue at risk",
  };
  return labels[reason] ?? titleCase(reason);
}

export function RailIntelligencePanel({ incidents, currency }: { incidents: RecoveryIncident[]; currency: string }) {
  if (incidents.length === 0) return <div className="rail-calm"><ShieldCheck size={28} /><div><strong>No active payment-rail incidents</strong><p>ReclaimRail does not invent degradation. Recovery policy is currently evaluating each case against normal rail conditions.</p></div></div>;
  return <div className="rail-intelligence">{incidents.map((incident) => { const baseline = Math.round(incident.baseline_failure_rate * 100); const current = Math.round(incident.failure_rate * 100); return <article className="rail-card" key={incident.incident_id}><div className="rail-card__heading"><div><p className="kicker">{titleCase(incident.severity)} severity · {titleCase(incident.scope)}</p><h3>{titleCase(incident.dimension_value)} payment degradation</h3></div><span className="badge badge--danger">{titleCase(incident.status)}</span></div><div className="rail-card__metrics"><div><span>Baseline failure rate</span><strong>{baseline}%</strong></div><div><span>Current failure rate</span><strong>{current}%</strong></div><div><span>Revenue at risk</span><strong>{formatMoney(incident.revenue_at_risk_minor, currency)}</strong></div><div><span>Detection evidence strength</span><strong>{Math.round(incident.confidence * 100)}%</strong></div></div><div className="rail-rate"><span>Failure-rate movement</span><div><i style={{ width: `${Math.min(100, Math.max(4, baseline))}%` }} /><b style={{ width: `${Math.min(100, Math.max(4, current))}%` }} /></div><small>Baseline <TrendingDown size={13} /> Current</small></div><div className="rail-card__impact"><AlertTriangle size={18} /><div><strong>Why the detector opened this incident</strong><p>{incident.reason_codes.map(reasonLabel).join(" · ")}</p></div></div><div className="rail-card__impact"><AlertTriangle size={18} /><div><strong>Recovery impact</strong><p>{impactFor(incident)}</p></div></div><footer>{incident.occurrence_count} provider observations · last seen {formatTimestamp(incident.last_detected_at)}. Detection evidence strength is calculated from sample size, baseline history, and failure-rate deviation—not by Gemini.</footer></article>; })}</div>;
}
