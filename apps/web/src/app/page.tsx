import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  ExternalLink,
  FileSearch,
  Play,
  ShieldCheck,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { DashboardLiveRefresh } from "@/components/dashboard-live-refresh";
import { RelativeTimestamp } from "@/components/live-time";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import {
  type RecoveryCaseQueueItem,
  type RecoveryDashboardSummary,
  type RecoveryIncident,
  type RecoveryOutcome,
  loadRecoveryDashboard,
} from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

export const dynamic = "force-dynamic";

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

function OperationsSignal({ label, value, description, tone, icon: Icon }: { label: string; value: string; description: string; tone: "risk" | "verified" | "protected" | "neutral"; icon: LucideIcon }) {
  return <article className={`operations-signal operations-signal--${tone}`}><Icon size={18} aria-hidden="true" /><div><span>{label}</span><strong>{value}</strong><small>{description}</small></div></article>;
}

function IncidentPanel({ incidents, currency }: { incidents: RecoveryIncident[]; currency: string }) {
  if (incidents.length === 0) {
    return <div className="calm-empty-state"><span className="calm-empty-state__check">✓</span><div><strong>No active payment-rail incidents</strong><p>Recovery automation is not currently restricted by a detected payment-method degradation.</p></div></div>;
  }
  return <div className="incident-stack">{incidents.map((incident) => <article className="incident-item" key={incident.incident_id}>
    <div className="incident-item__topline"><span className={`severity severity--${incident.severity}`}>{titleCase(incident.severity)} severity</span><Badge value={incident.status} /></div>
    <h3>{titleCase(incident.dimension_value)} payment degradation</h3>
    <p>Failure rate <strong>{Math.round(incident.failure_rate * 100)}%</strong> against a {Math.round(incident.baseline_failure_rate * 100)}% baseline.</p>
    <div className="incident-rate-meter" aria-label={`Current failure rate ${Math.round(incident.failure_rate * 100)} percent against baseline ${Math.round(incident.baseline_failure_rate * 100)} percent`}>
      <div><span>Baseline</span><i style={{ width: `${Math.min(100, incident.baseline_failure_rate * 1000)}%` }} /></div>
      <div><span>Current</span><i style={{ width: `${Math.min(100, incident.failure_rate * 1000)}%` }} /></div>
    </div>
    <div className="incident-item__details"><span>{formatMoney(incident.revenue_at_risk_minor, currency)} exposed</span><span>{incident.occurrence_count} observations</span></div>
  </article>)}</div>;
}

function RecoveryQueue({ cases, currency, liveCaseId }: { cases: RecoveryCaseQueueItem[]; currency: string; liveCaseId: string | null }) {
  if (cases.length === 0) {
    return <div className="queue-empty"><strong>No active recovery cases</strong><p>Run a scenario to see ReclaimRail detect, plan, execute, and reconcile a recovery safely.</p></div>;
  }
  return <div className="recovery-queue-table">
    <div className="recovery-queue-table__header"><span>Recovery case</span><span>Payment rail</span><span>Policy</span><span>Next action</span><span>Amount</span><span /></div>
    {cases.map((recoveryCase) => {
      const policy = recoveryCase.latest_action_policy_outcome;
      const PolicyIcon = policy === "allow" ? CheckCircle2 : AlertTriangle;
      const isLiveCase = recoveryCase.recovery_case_id === liveCaseId;
      const awaitingPayment = recoveryCase.latest_action_type === "create_payment_link" && recoveryCase.latest_action_status === "succeeded" && (recoveryCase.outcome_status === null || recoveryCase.outcome_status === "payment_link_pending");
      const nextAction = awaitingPayment
        ? "Awaiting recovery payment"
        : recoveryCase.outcome_status
          ? titleCase(recoveryCase.outcome_status)
          : recoveryCase.latest_action_type === null
            ? "Awaiting plan"
            : titleCase(recoveryCase.latest_action_type);
      const nextActionDetail = awaitingPayment
        ? "Provider reconciliation pending"
        : formatTimestamp(recoveryCase.next_action_at);
      return <Link className={`recovery-queue-row${isLiveCase ? " recovery-queue-row--live" : ""}`} href={`/cases/${recoveryCase.recovery_case_id}`} key={recoveryCase.recovery_case_id}>
        <span className="recovery-queue-row__case"><strong>CASE-{shortId(recoveryCase.recovery_case_id)}</strong>{isLiveCase ? <span className="live-case-badge"><i />Live now</span> : <Badge value={awaitingPayment ? "payment_link_pending" : recoveryCase.status} />}</span>
        <span>{recoveryCase.payment_method === null ? "Unknown" : titleCase(recoveryCase.payment_method)}</span>
        <span className={`recovery-queue-row__policy recovery-queue-row__policy--${badgeTone(policy)}`}><PolicyIcon size={16} /><span><strong>{policy === null ? "Pending" : titleCase(policy)}</strong><small>{policy === null ? "Awaiting evaluation" : "Deterministic policy"}</small></span></span>
        <span><strong>{nextAction}</strong><small>{nextActionDetail}</small></span>
        <span className="amount-cell">{formatMoney(recoveryCase.amount_minor, currency)}</span>
        <ArrowRight className="recovery-queue-row__arrow" size={18} />
      </Link>;
    })}
  </div>;
}

function OutcomeList({ outcomes, currency }: { outcomes: RecoveryOutcome[]; currency: string }) {
  if (outcomes.length === 0) return <p className="list-empty">No provider-verified outcomes have been reconciled yet.</p>;
  return <div className="outcome-list">{outcomes.map((outcome) => {
    const recovered = outcome.gross_recovered_minor - outcome.reversed_minor;
    const isRecovered = recovered > 0;
    const isDuplicatePrevention = outcome.status === "duplicate_collection_prevented";
    const value = isRecovered ? recovered : isDuplicatePrevention ? outcome.duplicate_collection_prevented_minor : 0;
    const valueLabel = isRecovered ? "Verified recovered" : isDuplicatePrevention ? "Duplicate prevented" : "Awaiting provider payment";
    return <article className="outcome-row" key={outcome.recovery_outcome_id}>
      <div><Badge value={outcome.status} /><p>{titleCase(outcome.attribution)}</p><Link className="outcome-case-link" href={`/cases/${outcome.recovery_case_id}`}>View case evidence</Link><small>{outcome.evidence_event_count} linked evidence events</small></div>
      <div className={`outcome-row__amount ${isRecovered ? "outcome-row__amount--verified" : isDuplicatePrevention ? "outcome-row__amount--protected" : ""}`}><strong>{formatMoney(value, currency)}</strong><span>{valueLabel}</span></div>
    </article>;
  })}</div>;
}

function CommandCenter({ summary, incidents, cases, outcomes, liveCaseId }: { summary: RecoveryDashboardSummary; incidents: RecoveryIncident[]; cases: RecoveryCaseQueueItem[]; outcomes: RecoveryOutcome[]; liveCaseId: string | null }) {
  const currency = summary.currency;
  return <div className="app-shell"><RecoveryNavigation /><main className="workspace operations-workspace" id="overview">
    <DashboardLiveRefresh />
    <header className="operations-hero">
      <div>
        <p className="kicker">Merchant recovery operations</p>
        <h1>Recover revenue.<br /><em>Keep control.</em></h1>
        <p>ReclaimRail connects payment evidence, Gemini’s bounded proposal, deterministic policy, and provider-confirmed outcomes—without pretending an action succeeded.</p>
        <div className="operations-hero__meta"><span className="test-mode"><i /> Razorpay Test Mode</span><span className="updated-at"><Clock3 size={15} /> Synced <RelativeTimestamp value={summary.generated_at} /></span></div>
      </div>
      <aside className="operations-hero__contract" aria-label="Recovery contract">
        <span>Recovery contract</span>
        <strong>AI proposes<br />Policy decides<br />Provider proves</strong>
        <small>Each layer leaves an inspectable evidence trail.</small>
      </aside>
    </header>
    <Link className="operations-runway" href="/payment-lab"><span className="operations-runway__icon"><Play size={20} fill="currentColor" /></span><span><em>Judge-ready live run</em><strong>Trigger a real Razorpay Test Mode failure and watch only persisted evidence move.</strong></span><span className="operations-runway__action">Open Payment Lab <ArrowRight size={18} /></span></Link>
    <section className="operations-signal-strip" aria-label="Verified recovery metrics">
      <OperationsSignal icon={TrendingUp} label="Revenue at risk" value={formatMoney(summary.revenue_at_risk_minor, currency)} description={`${summary.active_case_count} active recovery cases`} tone="risk" />
      <OperationsSignal icon={CircleDollarSign} label="Verified recovered" value={formatMoney(summary.verified_recovered_minor, currency)} description={`${summary.recovered_case_count} provider-confirmed cases`} tone="verified" />
      <OperationsSignal icon={ShieldCheck} label="Safety protected" value={formatMoney(summary.duplicate_collection_prevented_minor, currency)} description="Reconciled late-authorization cases" tone="protected" />
      <OperationsSignal icon={AlertTriangle} label="Open incidents" value={String(summary.open_incident_count)} description={`${formatMoney(summary.active_incident_revenue_at_risk_minor, currency)} currently exposed`} tone="neutral" />
    </section>
    <section className="workspace-grid operations-grid" id="incidents"><section className="panel panel--wide operations-panel"><div className="panel-heading"><div><p className="kicker">Payment-rail context</p><h2>Incidents that change recovery decisions</h2></div><span className="count-label">{summary.open_incident_count} active</span></div><IncidentPanel incidents={incidents} currency={currency} /></section>
      <aside className="panel policy-summary operations-policy" id="safety-controls"><ShieldCheck className="policy-summary__icon" size={30} /><p className="kicker">Bounded automation</p><h2>AI proposes. Policy decides.</h2><p>Gemini can recommend an intervention. Deterministic controls decide whether money-facing actions may happen.</p><ul><li><Check size={16} />Consent and quiet-hour checks</li><li><Check size={16} />Active-incident circuit breaker</li><li><Check size={16} />Idempotent payment-link execution</li><li><Check size={16} />Late-authorization stop rules</li><li><Check size={16} />Tamper-evident audit chain</li></ul></aside>
    </section>
    <section className="panel operations-panel operations-panel--queue" id="recovery-queue"><div className="panel-heading"><div><p className="kicker">Bounded execution queue</p><h2>Recovery cases requiring attention</h2></div><span className="count-label">{summary.active_case_count} active</span></div><RecoveryQueue cases={cases} currency={currency} liveCaseId={liveCaseId} /></section>
    <section className="workspace-grid workspace-grid--outcomes operations-grid" id="outcomes"><section className="panel operations-panel"><div className="panel-heading"><div><p className="kicker">Verified outcome ledger</p><h2>Measured recovery, backed by evidence</h2></div><span className="count-label">{summary.pending_outcome_count} pending</span></div><OutcomeList outcomes={outcomes} currency={currency} /></section>
      <aside className="audit-callout operations-audit"><FileSearch size={31} /><p className="kicker">Audit-ready</p><h2>Every action can be traced to a verified outcome.</h2><p>Case detail exposes the failure, Gemini proposal, policy decision, provider action, outcome proof, and hash-chain timeline.</p><Link href="#recovery-queue">Inspect a recovery case <ExternalLink size={16} /></Link></aside>
    </section>
  </main></div>;
}

function UnavailableDashboard() {
  return <div className="app-shell"><RecoveryNavigation /><main className="workspace workspace--unavailable"><section className="unavailable-card"><p className="kicker">Live data unavailable</p><h1>Start the ReclaimRail API to open the command center.</h1><p>This interface never substitutes invented numbers. Once the API is running, refresh to load the real recovery ledger.</p><code>uv --directory apps/api run fastapi dev app/main.py</code></section></main></div>;
}

export default async function Home({ searchParams }: { searchParams: Promise<{ liveCase?: string }> }) {
  const { liveCase } = await searchParams;
  const dashboard = await loadRecoveryDashboard().catch(() => null);
  if (dashboard === null) return <UnavailableDashboard />;
  return <CommandCenter summary={dashboard.summary} incidents={dashboard.incidents} cases={dashboard.cases.items} outcomes={dashboard.outcomes.items} liveCaseId={liveCase ?? null} />;
}
