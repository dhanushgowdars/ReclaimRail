import {
  type RecoveryCaseQueueItem,
  type RecoveryDashboardSummary,
  type RecoveryIncident,
  type RecoveryOutcome,
  loadRecoveryDashboard,
} from "@/lib/recovery-api";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import Link from "next/link";

export const dynamic = "force-dynamic";

function formatMoney(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

function formatTimestamp(timestamp: string | null): string {
  if (timestamp === null) return "Not scheduled";
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortId(value: string): string {
  return value.slice(0, 8).toUpperCase();
}

function badgeTone(value: string | null): string {
  if (value === null) return "neutral";
  if (["recovered", "succeeded", "allow", "allowed", "open"].includes(value)) return "success";
  if (["blocked", "cancelled", "escalated", "failed", "stopped"].includes(value)) return "danger";
  if (["waiting", "executing", "scheduled", "payment_link_pending"].includes(value)) return "warning";
  if (value === "duplicate_collection_prevented") return "protected";
  return "neutral";
}

function Badge({ value }: { value: string | null }) {
  return <span className={`badge badge--${badgeTone(value)}`}>{value === null ? "Not available" : titleCase(value)}</span>;
}

function MetricCard({ label, value, description, tone }: { label: string; value: string; description: string; tone: "risk" | "verified" | "protected" | "neutral" }) {
  return <article className={`metric-card metric-card--${tone}`}><p>{label}</p><strong>{value}</strong><span>{description}</span></article>;
}

function IncidentPanel({ incidents, currency }: { incidents: RecoveryIncident[]; currency: string }) {
  if (incidents.length === 0) {
    return <div className="calm-empty-state"><span className="calm-empty-state__check">✓</span><div><strong>No active payment-rail incidents</strong><p>Recovery automation is not currently restricted by a detected payment-method degradation.</p></div></div>;
  }
  return <div className="incident-stack">{incidents.map((incident) => <article className="incident-item" key={incident.incident_id}>
    <div className="incident-item__topline"><span className={`severity severity--${incident.severity}`}>{titleCase(incident.severity)} severity</span><Badge value={incident.status} /></div>
    <h3>{titleCase(incident.dimension_value)} payment degradation</h3>
    <p>Failure rate <strong>{Math.round(incident.failure_rate * 100)}%</strong> against a {Math.round(incident.baseline_failure_rate * 100)}% baseline.</p>
    <div className="incident-item__details"><span>{formatMoney(incident.revenue_at_risk_minor, currency)} exposed</span><span>{incident.occurrence_count} observations</span></div>
  </article>)}</div>;
}

function RecoveryQueue({ cases, currency }: { cases: RecoveryCaseQueueItem[]; currency: string }) {
  if (cases.length === 0) {
    return <div className="queue-empty"><strong>No active recovery cases</strong><p>Run a scenario to see ReclaimRail detect, plan, execute, and reconcile a recovery safely.</p></div>;
  }
  return <div className="table-wrap"><table><thead><tr><th>Recovery case</th><th>Payment rail</th><th>Policy</th><th>Next action</th><th className="align-right">Amount</th></tr></thead><tbody>{cases.map((recoveryCase) => <tr key={recoveryCase.recovery_case_id}>
    <td><Link className="case-id case-id--link" href={`/cases/${recoveryCase.recovery_case_id}`}>CASE-{shortId(recoveryCase.recovery_case_id)}</Link><Badge value={recoveryCase.status} /></td>
    <td>{recoveryCase.payment_method === null ? "Unknown" : titleCase(recoveryCase.payment_method)}</td>
    <td><Badge value={recoveryCase.latest_action_policy_outcome} /><small>{recoveryCase.latest_action_policy_outcome === null ? "Awaiting policy evaluation" : "Deterministic policy evaluated"}</small></td>
    <td><strong>{recoveryCase.latest_action_type === null ? "Awaiting plan" : titleCase(recoveryCase.latest_action_type)}</strong><small>{formatTimestamp(recoveryCase.next_action_at)}</small></td>
    <td className="align-right amount-cell">{formatMoney(recoveryCase.amount_minor, currency)}</td>
  </tr>)}</tbody></table></div>;
}

function OutcomeList({ outcomes, currency }: { outcomes: RecoveryOutcome[]; currency: string }) {
  if (outcomes.length === 0) return <p className="list-empty">No provider-verified outcomes have been reconciled yet.</p>;
  return <div className="outcome-list">{outcomes.map((outcome) => {
    const recovered = outcome.gross_recovered_minor - outcome.reversed_minor;
    const isRecovered = recovered > 0;
    const value = isRecovered ? recovered : outcome.duplicate_collection_prevented_minor;
    return <article className="outcome-row" key={outcome.recovery_outcome_id}>
      <div><Badge value={outcome.status} /><p>{titleCase(outcome.attribution)}</p><Link className="outcome-case-link" href={`/cases/${outcome.recovery_case_id}`}>View case evidence</Link><small>{outcome.evidence_event_count} linked evidence events</small></div>
      <div className={`outcome-row__amount ${isRecovered ? "outcome-row__amount--verified" : "outcome-row__amount--protected"}`}><strong>{formatMoney(value, currency)}</strong><span>{isRecovered ? "Verified recovered" : "Duplicate prevented"}</span></div>
    </article>;
  })}</div>;
}

function CommandCenter({ summary, incidents, cases, outcomes }: { summary: RecoveryDashboardSummary; incidents: RecoveryIncident[]; cases: RecoveryCaseQueueItem[]; outcomes: RecoveryOutcome[] }) {
  const currency = summary.currency;
  return <div className="app-shell"><RecoveryNavigation /><main className="workspace" id="overview">
    <header className="workspace-header"><div><p className="kicker">Merchant operations</p><h1>Recovery command center</h1></div><div className="workspace-header__actions"><Link className="lab-launch-link" href="/payment-lab">Run live recovery</Link><span className="test-mode"><i />Test mode</span><span className="updated-at">Updated {formatTimestamp(summary.generated_at)}</span><Link className="refresh-link" href="/">Refresh data</Link></div></header>
    <section className="metrics-grid" aria-label="Verified recovery metrics">
      <MetricCard label="Revenue at risk" value={formatMoney(summary.revenue_at_risk_minor, currency)} description={`${summary.active_case_count} active recovery cases`} tone="risk" />
      <MetricCard label="Verified recovered" value={formatMoney(summary.verified_recovered_minor, currency)} description={`${summary.recovered_case_count} confirmed cases`} tone="verified" />
      <MetricCard label="Duplicate prevented" value={formatMoney(summary.duplicate_collection_prevented_minor, currency)} description="Late-authorization safety value" tone="protected" />
      <MetricCard label="Open incidents" value={String(summary.open_incident_count)} description={`${formatMoney(summary.active_incident_revenue_at_risk_minor, currency)} currently exposed`} tone="neutral" />
    </section>
    <section className="workspace-grid" id="incidents"><section className="panel panel--wide"><div className="panel-heading"><div><p className="kicker">Payment-rail context</p><h2>Incidents that change recovery decisions</h2></div><span className="count-label">{summary.open_incident_count} active</span></div><IncidentPanel incidents={incidents} currency={currency} /></section>
      <aside className="panel policy-summary" id="safety-controls"><p className="kicker">Bounded automation</p><h2>AI proposes. Policy decides.</h2><p>Gemini can recommend an intervention. Deterministic controls decide whether money-facing actions may happen.</p><ul><li>Consent and quiet-hour checks</li><li>Active-incident circuit breaker</li><li>Idempotent payment-link execution</li><li>Late-authorization stop rules</li><li>Tamper-evident audit chain</li></ul></aside>
    </section>
    <section className="panel" id="recovery-queue"><div className="panel-heading"><div><p className="kicker">Bounded execution queue</p><h2>Recovery cases requiring attention</h2></div><span className="count-label">{summary.active_case_count} active</span></div><RecoveryQueue cases={cases} currency={currency} /></section>
    <section className="workspace-grid workspace-grid--outcomes" id="outcomes"><section className="panel"><div className="panel-heading"><div><p className="kicker">Verified outcome ledger</p><h2>Measured recovery, backed by evidence</h2></div><span className="count-label">{summary.pending_outcome_count} pending</span></div><OutcomeList outcomes={outcomes} currency={currency} /></section>
      <aside className="audit-callout"><p className="kicker">Audit-ready</p><h2>Every action can be traced to a verified outcome.</h2><p>Case detail will expose the payment lifecycle, Gemini proposal, policy decision, provider action, outcome proof, and hash-chain timeline.</p></aside>
    </section>
  </main></div>;
}

function UnavailableDashboard() {
  return <div className="app-shell"><RecoveryNavigation /><main className="workspace workspace--unavailable"><section className="unavailable-card"><p className="kicker">Live data unavailable</p><h1>Start the ReclaimRail API to open the command center.</h1><p>This interface never substitutes invented numbers. Once the API is running, refresh to load the real recovery ledger.</p><code>uv --directory apps/api run fastapi dev app/main.py</code></section></main></div>;
}

export default async function Home() {
  const dashboard = await loadRecoveryDashboard().catch(() => null);
  if (dashboard === null) return <UnavailableDashboard />;
  return <CommandCenter summary={dashboard.summary} incidents={dashboard.incidents} cases={dashboard.cases.items} outcomes={dashboard.outcomes.items} />;
}
