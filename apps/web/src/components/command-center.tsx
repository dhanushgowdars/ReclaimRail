import {
  ArrowRight,
  BrainCircuit,
  CircleDollarSign,
  FlaskConical,
  PlayCircle,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { DashboardLiveRefresh } from "@/components/dashboard-live-refresh";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import {
  type RecoveryCaseQueueItem,
  type RecoveryDashboardSummary,
} from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

function stateTone(value: string): string {
  if (["recovered", "allow", "allowed"].includes(value)) return "success";
  if (["blocked", "cancelled", "stopped", "closed_without_execution"].includes(value)) return "danger";
  if (value === "escalated") return "protected";
  return "warning";
}

function businessStatus(item: RecoveryCaseQueueItem): string {
  if (item.outcome_status === "recovered" || item.status === "recovered") return "recovered";
  if (["rejected", "expired"].includes(item.latest_approval_status ?? "")) return "closed_without_execution";
  if (["cancelled", "stopped", "blocked", "exhausted"].includes(item.status)) return "closed_without_execution";
  if (item.latest_approval_status === "pending") return "human_review";
  if (item.outcome_status !== null) return item.outcome_status;
  if (item.status === "escalated") return "needs_attention";
  return item.latest_action_policy_outcome ?? item.status;
}

export function CommandCenter({
  summary,
  cases,
}: {
  summary: RecoveryDashboardSummary;
  cases: RecoveryCaseQueueItem[];
}) {
  const recentCases = [...cases]
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
    .slice(0, 6);
  const escalations = cases.filter((item) => item.latest_approval_status === "pending").length;
  const awaitingProvider = summary.pending_outcome_count;
  const stopped = cases.filter((item) =>
    ["cancelled", "stopped", "blocked"].includes(item.status) ||
    ["block", "stop"].includes(item.latest_action_policy_outcome ?? ""),
  ).length;

  return (
    <div className="app-shell">
      <RecoveryNavigation active="overview" />
      <DashboardLiveRefresh />
      <main className="workspace command-center">
        <header className="command-center__hero">
          <div>
            <p className="kicker">Evidence-first recovery operations</p>
            <h1>Recovery command center</h1>
            <p>
              Watch provider-confirmed payment failures move through AI recommendation,
              deterministic policy, controlled action, and provider-confirmed recovery.
            </p>
          </div>
          <Link className="command-center__start" href="/payment-lab">
            <PlayCircle size={19} /> Start live Test Mode run <ArrowRight size={17} />
          </Link>
        </header>

        <section className="command-center__control-path" aria-label="Recovery control path">
          <header><p className="kicker">One controlled recovery path</p><h2>From verified failure to financial proof</h2><span>Each stage advances only when its recorded evidence exists.</span></header>
          <ol>
            <li><b>01</b><div><strong>Provider evidence</strong><span>Razorpay confirms the payment failure.</span></div></li>
            <li><b>02</b><div><strong>Gemini proposal</strong><span>The agent cites evidence and proposes one bounded plan.</span></div></li>
            <li><b>03</b><div><strong>Policy control</strong><span>Rules—and a human when required—authorise the action.</span></div></li>
            <li><b>04</b><div><strong>Outcome proof</strong><span>Razorpay payment confirmation changes recovered revenue.</span></div></li>
          </ol>
          <p><BrainCircuit size={18} /><strong>Control boundary:</strong> AI recommends; policy and authorised humans decide; Razorpay proves the result.</p>
        </section>

        <section className="command-center__metrics" aria-label="Live recovery state">
          <article className="is-active"><span>Open recovery records</span><strong>{summary.active_case_count}</strong><small>Actionable cases plus historical escalations awaiting a recorded disposition</small></article>
          <article className="is-risk"><span>Amount under control</span><strong>{formatMoney(summary.revenue_at_risk_minor, summary.currency)}</strong><small>Original payment value; not recovered revenue</small></article>
          <article className="is-recovered"><span>Provider-confirmed recovered</span><strong>{formatMoney(summary.verified_recovered_minor, summary.currency)}</strong><small>{summary.recovered_case_count} recovered case{summary.recovered_case_count === 1 ? "" : "s"}</small></article>
          <article className="is-protected"><span>Pending provider outcomes</span><strong>{summary.pending_outcome_count}</strong><small>Recorded recovery value that is not revenue yet</small></article>
        </section>

        <section className="command-center__grid">
          <article className="command-center__panel">
            <div className="command-center__panel-heading"><div><p className="kicker">Connected case evidence</p><h2>Latest recovery cases</h2></div><Link href="/cases">Open all cases <ArrowRight size={15} /></Link></div>
            {recentCases.length === 0 ? <p className="command-center__empty">No recovery cases yet. Start a Test Mode run to create provider-backed evidence.</p> : <div className="command-center__case-list">{recentCases.map((item) => {
              const status = businessStatus(item);
              const reviewEvidence = item.latest_approval_status === "approved" ? "Review approved" : item.latest_approval_status === "rejected" ? "Review rejected" : item.latest_approval_status === "expired" ? "Review expired without a decision" : item.latest_approval_status === "pending" ? "Review pending" : null;
              return <Link key={item.recovery_case_id} href={`/cases/${item.recovery_case_id}`}><div><strong>CASE-{shortId(item.recovery_case_id)}</strong><span>{titleCase(item.payment_method ?? "payment rail")} · updated {formatTimestamp(item.updated_at)}</span>{reviewEvidence ? <small>{reviewEvidence}{item.latest_approval_decision_reason ? ` · ${item.latest_approval_decision_reason}` : ""}</small> : null}</div><em className={`badge badge--${stateTone(status)}`}>{titleCase(status)}</em><b>{formatMoney(item.amount_minor, item.currency)}</b><ArrowRight size={16} /></Link>;
            })}</div>}
          </article>

          <aside className="command-center__attention">
            <p className="kicker">Operator attention</p>
            <h2>What needs action now</h2>
            <Link className="is-review" href="/reviews"><span><strong>{escalations}</strong><small>Real pending approval records</small></span><b>Review</b></Link>
            <Link className="is-provider" href="/cases"><span><strong>{awaitingProvider}</strong><small>Awaiting Razorpay outcome</small></span><b>Inspect</b></Link>
            <Link className="is-stopped" href="/cases"><span><strong>{stopped}</strong><small>Closed without execution</small></span><b>Inspect</b></Link>
            <div className="command-center__evidence-links"><span>Inspect system proof</span><Link href="/intelligence"><BrainCircuit size={21} /> Recovery Brain</Link><Link href="/outcomes"><CircleDollarSign size={21} /> Outcome Ledger</Link><Link href="/evaluations"><FlaskConical size={21} /> Evidence Lab</Link><Link href="/safety-controls"><ShieldCheck size={21} /> Safety Controls</Link></div>
          </aside>
        </section>
      </main>
    </div>
  );
}
