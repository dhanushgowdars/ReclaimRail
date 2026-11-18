import { BrainCircuit, ExternalLink, FileCheck2, ShieldCheck, UserCheck } from "lucide-react";
import Link from "next/link";
import { type RecoveryCaseQueueItem, type RecoveryDashboardSummary, type WorkerFleetHealth } from "@/lib/recovery-api";

const policyFlow = [
  { step: "01", title: "AI proposes", detail: "Gemini diagnoses signed failure evidence and recommends one bounded action.", icon: BrainCircuit },
  { step: "02", title: "Policy evaluates", detail: "Deterministic checks evaluate state, amount, attempts, incidents, consent, and duplication risk.", icon: ShieldCheck },
  { step: "03", title: "Human authorizes", detail: "Protected actions pause for an accountable decision that releases only the recorded action.", icon: UserCheck },
  { step: "04", title: "Provider proves", detail: "Razorpay evidence—not AI or browser state—determines whether recovery is recorded.", icon: FileCheck2 },
] as const;

const rules = [
  ["Original payment completion stop", "Signed payment status", "Original payment must remain failed and recovery-eligible.", "Stop when Razorpay reports authorization or capture.", "Prevents collecting the same obligation twice."],
  ["Late authorization compensation", "Original payment events + active recovery link", "Late original authorization invalidates the outstanding recovery action.", "Cancel the link or escalate cancellation failure.", "Closes the race between recovery and delayed authorization."],
  ["Bounded attempt limit", "Persisted execution-attempt count", "Attempts must remain below the configured maximum.", "Block further provider execution when exhausted.", "Prevents retry storms and uncontrolled provider calls."],
  ["Provider-read retry containment", "Persisted reconciliation cooldown, circuit, and retry budget", "Unavailable provider reads cannot run on every worker poll; equivalent failures remain bounded.", "Defer, open the circuit, or exhaust the recorded budget.", "Prevents evidence growth, truth-version amplification, and provider-read storms."],
  ["Incident circuit breaker", "Active payment-rail incident severity", "High or critical degradation cannot receive blind automated intervention.", "Block or escalate from the recorded incident state.", "Avoids amplifying a provider-wide outage."],
  ["Exact financial match", "Case amount, currency, and active-link state", "Link must match the original amount/currency and no duplicate may exist.", "Allow one idempotent link; otherwise block.", "Prevents amount drift and duplicate recovery links."],
  ["Consent and quiet-period boundary", "Approved channel, consent, and contact timing", "Contact requires an allowed channel and applicable consent/timing checks.", "Send only through the permitted path or make no attempt.", "Separates financial authority from communication authority."],
  ["Protected human approval", "Amount threshold + exact persisted action", "Protected actions cannot execute while approval is pending or expired.", "Approve or reject the recorded action; hard checks remain non-overridable.", "Adds accountability without bypassing safety."],
  ["Provider-confirmed accounting", "Paid link webhook or verified provider lookup", "Created/opened links are not revenue; payment must be provider-confirmed.", "Write one linked outcome and close the case as recovered.", "Keeps the Outcome Ledger financially defensible."],
] as const;

function displayMetric(value: number | string | boolean | null | undefined): string {
  if (value === undefined || value === null) return "Unavailable";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function SafetyControlsPanel({ summary, cases, workerHealth }: { summary: RecoveryDashboardSummary; cases: RecoveryCaseQueueItem[]; workerHealth: WorkerFleetHealth | null }) {
  const reconciliationWorker = workerHealth?.workers.find((worker) => worker.name === "payment_lab_recovery");
  const metrics = reconciliationWorker?.metrics ?? {};
  const containmentMetrics = [
    ["Worker", "Payment Lab recovery", "The supervised worker that performs payment-truth reconciliation."],
    ["Status", reconciliationWorker?.status ?? "unavailable", "Current persisted worker-heartbeat state."],
    ["Provider calls this batch", displayMetric(metrics.truth_reconciliation_provider_calls), "Actual provider reads made by the latest batch."],
    ["Unavailable this batch", displayMetric(metrics.truth_reconciliation_unavailable), "Provider reads that failed safely in the latest batch."],
    ["Cooling controls", displayMetric(metrics.truth_reconciliation_cooling_controls), "Attempts deferred by persisted cooldown or backoff."],
    ["Open circuits", displayMetric(metrics.truth_reconciliation_open_circuit_controls), "Attempts blocked by a persisted open circuit."],
    ["Exhausted controls", displayMetric(metrics.truth_reconciliation_exhausted_controls), "Attempts whose bounded provider-read budget is exhausted."],
    ["Synthetic blocks", displayMetric(metrics.truth_reconciliation_synthetic_blocked_controls), "Controlled synthetic identifiers stopped before a live adapter."],
  ] as const;
  return <div className="safety-policy">
    <section className="safety-policy__contract"><div><p className="kicker">Executable governance contract</p><h2>AI recommends. Policy authorizes. Razorpay proves.</h2><p>This page documents the controls used in the live recovery path. Gemini cannot call a payment provider, change an amount, bypass approval, or declare revenue recovered. Every executable decision is derived from stored evidence and leaves an inspectable receipt.</p></div><div className="safety-policy__boundary"><ShieldCheck size={26} /><span>Control boundary</span><strong>Recommendation ≠ permission ≠ financial proof</strong></div></section>
    <section className="safety-policy__flow" aria-label="Recovery decision flow">{policyFlow.map(({ step, title, detail, icon: Icon }) => <article key={step}><div><span>{step}</span><Icon size={20} /></div><strong>{title}</strong><p>{detail}</p></article>)}</section>
    <section className="safety-policy__matrix"><header><p className="kicker">Deterministic policy rulebook</p><h2>What is checked, why it exists, and what it can do</h2><p>Rules evaluate persisted case/provider data. An AI explanation helps a reviewer understand a proposal, but never supplies permission.</p></header><div className="safety-policy__table-wrap"><table><thead><tr><th>Control</th><th>Evidence evaluated</th><th>Enforced rule</th><th>Resulting action</th><th>Why it matters</th></tr></thead><tbody>{rules.map(([control, evidence, rule, decision, purpose]) => <tr key={control}><td><ShieldCheck size={17} /><strong>{control}</strong></td><td>{evidence}</td><td>{rule}</td><td>{decision}</td><td>{purpose}</td></tr>)}</tbody></table></div></section>
    <section className="safety-policy__matrix safety-policy__containment"><header><p className="kicker">Live containment evidence</p><h2>Provider-read reconciliation is bounded and observable</h2><p>These values come from the Payment Lab recovery worker heartbeat. They expose actual calls and persisted cooldown, circuit, exhausted-budget, and synthetic-block controls rather than hiding them in logs.</p></header><dl className="safety-policy__containment-grid" aria-label="Payment Lab recovery containment evidence">{containmentMetrics.map(([label, value, detail]) => <div key={label}><dt>{label}</dt><dd>{value}</dd><small>{detail}</small></div>)}</dl></section>
    <section className="safety-policy__proof"><div><p className="kicker">Verify, do not trust the page</p><h2>Every claim links back to a case receipt</h2><p>Inspect the proposed action, policy outcome, approval, provider execution, payment confirmation, and tamper-evident audit chain.</p></div><Link href="/cases">Open real case evidence <ExternalLink size={16} /></Link></section>
    <p className="safety-policy__scope">Policy reference scope: <strong>{cases.length} currently accessible case records</strong> and <strong>{summary.open_incident_count} active rail incident{summary.open_incident_count === 1 ? "" : "s"}</strong>. Case receipts—not aggregate counters—are the authoritative execution evidence.</p>
  </div>;
}
