import { ArrowRight, CircleDollarSign, Clock3, ExternalLink, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { RecoveryNavigation } from "@/components/recovery-navigation";
import { CaseExplorer } from "@/components/case-explorer";
import { OutcomeLedger } from "@/components/outcome-ledger";
import { RailIntelligencePanel } from "@/components/rail-intelligence-panel";
import { SafetyControlsPanel } from "@/components/safety-controls-panel";
import { type RecoveryCaseQueueItem, type RecoveryDashboardSummary, type RecoveryIncident, type RecoveryOutcome } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

type Section = "queue" | "reviews" | "outcomes" | "controls" | "intelligence";

const copy: Record<Section, { eyebrow: string; title: string; description: string }> = {
  queue: { eyebrow: "Recovery operations", title: "Recovery cases", description: "Every case starts from a provider-confirmed payment failure and remains linked to its decision and outcome evidence." },
  reviews: { eyebrow: "Protected automation", title: "Human review queue", description: "High-value or escalated recovery actions cannot execute until an authorized reviewer records a decision." },
  outcomes: { eyebrow: "Financial proof ledger", title: "Outcome ledger", description: "Revenue is counted only after Razorpay provider evidence is reconciled into the recovery ledger." },
  controls: { eyebrow: "Deterministic governance", title: "Safety controls", description: "Gemini can recommend; deterministic policy and provider evidence decide what ReclaimRail may do." },
  intelligence: { eyebrow: "Payment-rail context", title: "Rail intelligence", description: "Incident signals explain when payment-rail degradation changes or stops recovery behaviour." },
};

function Badge({ value }: { value: string | null }) {
  const tone = ["recovered", "allow", "succeeded"].includes(value ?? "") ? "success" : ["failed", "escalated", "blocked"].includes(value ?? "") ? "danger" : "warning";
  return <span className={`badge badge--${tone}`}>{value === null ? "Pending" : titleCase(value)}</span>;
}

function CaseRows({ items, currency }: { items: RecoveryCaseQueueItem[]; currency: string }) {
  if (items.length === 0) return <p className="detail-empty">No matching cases are waiting right now.</p>;
  return <div className="operations-list">{items.map((item) => <Link key={item.recovery_case_id} href={`/cases/${item.recovery_case_id}`} className="operations-list__row"><div><strong>CASE-{shortId(item.recovery_case_id)}</strong><span>{item.payment_method === null ? "Payment rail pending" : titleCase(item.payment_method)} · opened {formatTimestamp(item.opened_at)}</span></div><div><Badge value={item.latest_action_policy_outcome ?? item.status} /><span>{item.latest_action_type === null ? "Awaiting plan" : titleCase(item.latest_action_type)}</span></div><strong>{formatMoney(item.amount_minor, currency)}</strong><ArrowRight size={18} /></Link>)}</div>;
}

export function OperationsPage({ section, summary, cases, outcomes, incidents }: { section: Section; summary: RecoveryDashboardSummary; cases: RecoveryCaseQueueItem[]; outcomes: RecoveryOutcome[]; incidents: RecoveryIncident[] }) {
  const content = copy[section];
  const escalated = cases.filter((item) => item.latest_action_policy_outcome === "escalate" || item.status === "escalated");
  return <div className="app-shell"><RecoveryNavigation active={section} /><main className="workspace operations-page"><header className="operations-page__hero"><p className="kicker">{content.eyebrow}</p><h1>{content.title}</h1><p>{content.description}</p><span className="test-mode"><i /> Razorpay Test Mode · evidence-backed</span></header>
    {section === "queue" && <section className="panel"><div className="panel-heading"><div><p className="kicker">Active and recently resolved</p><h2>{summary.active_case_count} active recovery cases</h2></div><Link href="/payment-lab">Start a provider run <ExternalLink size={16} /></Link></div><CaseExplorer cases={cases} currency={summary.currency} /></section>}
    {section === "reviews" && <section className="panel"><div className="panel-heading"><div><p className="kicker">Approval boundary</p><h2>Decisions requiring human control</h2></div><ShieldCheck size={25} /></div><p className="operations-page__note">Only cases that policy escalates appear here. Every decision has the proposed action, guardrails, and case evidence behind it.</p><CaseRows items={escalated} currency={summary.currency} /></section>}
    {section === "outcomes" && <section className="panel"><div className="panel-heading"><div><p className="kicker">Provider-confirmed money state</p><h2>{formatMoney(summary.verified_recovered_minor, summary.currency)} verified recovered</h2></div><CircleDollarSign size={25} /></div><OutcomeLedger outcomes={outcomes} currency={summary.currency} /></section>}
    {section === "controls" && <SafetyControlsPanel summary={summary} cases={cases} />}
    {section === "intelligence" && <section className="panel"><div className="panel-heading"><div><p className="kicker">Degradation detection</p><h2>Signals that influence recovery</h2></div><Clock3 size={25} /></div><RailIntelligencePanel incidents={incidents} currency={summary.currency} /></section>}
  </main></div>;
}
