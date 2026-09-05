import { BrainCircuit, ExternalLink, FileCheck2, ShieldCheck, UserCheck } from "lucide-react";
import Link from "next/link";
import { type RecoveryCaseQueueItem, type RecoveryDashboardSummary } from "@/lib/recovery-api";

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
  ["Incident circuit breaker", "Active payment-rail incident severity", "High or critical degradation cannot receive blind automated intervention.", "Block or escalate from the recorded incident state.", "Avoids amplifying a provider-wide outage."],
  ["Exact financial match", "Case amount, currency, and active-link state", "Link must match the original amount/currency and no duplicate may exist.", "Allow one idempotent link; otherwise block.", "Prevents amount drift and duplicate recovery links."],
  ["Consent and quiet-period boundary", "Approved channel, consent, and contact timing", "Contact requires an allowed channel and applicable consent/timing checks.", "Send only through the permitted path or make no attempt.", "Separates financial authority from communication authority."],
  ["Protected human approval", "Amount threshold + exact persisted action", "Protected actions cannot execute while approval is pending or expired.", "Approve or reject the recorded action; hard checks remain non-overridable.", "Adds accountability without bypassing safety."],
  ["Provider-confirmed accounting", "Paid link webhook or verified provider lookup", "Created/opened links are not revenue; payment must be provider-confirmed.", "Write one linked outcome and close the case as recovered.", "Keeps the Outcome Ledger financially defensible."],
] as const;

export function SafetyControlsPanel({ summary, cases }: { summary: RecoveryDashboardSummary; cases: RecoveryCaseQueueItem[] }) {
  return <div className="safety-policy">
    <section className="safety-policy__contract"><div><p className="kicker">Executable governance contract</p><h2>AI recommends. Policy authorizes. Razorpay proves.</h2><p>This page documents the controls used in the live recovery path. Gemini cannot call a payment provider, change an amount, bypass approval, or declare revenue recovered. Every executable decision is derived from stored evidence and leaves an inspectable receipt.</p></div><div className="safety-policy__boundary"><ShieldCheck size={26} /><span>Control boundary</span><strong>Recommendation ≠ permission ≠ financial proof</strong></div></section>
    <section className="safety-policy__flow" aria-label="Recovery decision flow">{policyFlow.map(({ step, title, detail, icon: Icon }) => <article key={step}><div><span>{step}</span><Icon size={20} /></div><strong>{title}</strong><p>{detail}</p></article>)}</section>
    <section className="safety-policy__matrix"><header><p className="kicker">Deterministic policy rulebook</p><h2>What is checked, why it exists, and what it can do</h2><p>Rules evaluate persisted case/provider data. An AI explanation helps a reviewer understand a proposal, but never supplies permission.</p></header><div className="safety-policy__table-wrap"><table><thead><tr><th>Control</th><th>Evidence evaluated</th><th>Enforced rule</th><th>Resulting action</th><th>Why it matters</th></tr></thead><tbody>{rules.map(([control, evidence, rule, decision, purpose]) => <tr key={control}><td><ShieldCheck size={17} /><strong>{control}</strong></td><td>{evidence}</td><td>{rule}</td><td>{decision}</td><td>{purpose}</td></tr>)}</tbody></table></div></section>
    <section className="safety-policy__proof"><div><p className="kicker">Verify, do not trust the page</p><h2>Every claim links back to a case receipt</h2><p>Inspect the proposed action, policy outcome, approval, provider execution, payment confirmation, and tamper-evident audit chain.</p></div><Link href="/cases">Open real case evidence <ExternalLink size={16} /></Link></section>
    <p className="safety-policy__scope">Policy reference scope: <strong>{cases.length} currently accessible case records</strong> and <strong>{summary.open_incident_count} active rail incident{summary.open_incident_count === 1 ? "" : "s"}</strong>. Case receipts—not aggregate counters—are the authoritative execution evidence.</p>
  </div>;
}
