import { DashboardLiveRefresh } from "@/components/dashboard-live-refresh";
import {
  ExpiredReviewRecords,
  HumanReviewQueue,
} from "@/components/human-review-queue";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import { loadRecoveryApprovals } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function ReviewsPage() {
  const result = await Promise.all([
    loadRecoveryApprovals("pending"),
    loadRecoveryApprovals("expired"),
  ])
    .then(([approvals, expiredApprovals]) => ({
      approvals,
      expiredApprovals,
      unavailable: false,
    }))
    .catch(() => ({ approvals: [], expiredApprovals: [], unavailable: true }));

  return (
    <div className="app-shell">
      <RecoveryNavigation active="reviews" />
      <DashboardLiveRefresh />
      <main className="workspace operations-page review-workspace">
        <header className="operations-page__hero">
          <p className="kicker">Protected automation</p>
          <h1>Human review control</h1>
          <p>
            Review only payment-link actions at or above the configured ₹10,000
            protection threshold. Every decision and expiry is persisted with its case
            evidence and audit trail.
          </p>
          <span className="test-mode"><i /> Razorpay Test Mode · protected operator action</span>
        </header>

        <section className="review-explainer" aria-label="How human review works">
          <div>
            <p className="kicker">Purpose</p>
            <h2>Why a person enters the workflow</h2>
            <p>
              When a permitted recovery payment link is worth ₹10,000 or more,
              execution pauses for an authorised reviewer. Lower-value actions continue
              through deterministic policy without entering this queue.
            </p>
          </div>
          <ol>
            <li><b>01</b><span><strong>Threshold reached</strong><small>A permitted payment-link action is ₹10,000 or more.</small></span></li>
            <li><b>02</b><span><strong>Policy pauses</strong><small>The exact action cannot execute while approval is pending.</small></span></li>
            <li><b>03</b><span><strong>Decision or expiry</strong><small>The reviewer records a reason, or the unanswered request expires safely.</small></span></li>
            <li><b>04</b><span><strong>System updates</strong><small>Command Center, case state, queue, and audit trail refresh.</small></span></li>
          </ol>
          <p className="review-explainer__boundary">
            <strong>Safety boundary:</strong> Approval releases only the reviewed action.
            It cannot override a policy block or prove revenue; Razorpay payment
            confirmation still proves the financial result.
          </p>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="kicker">Action required now</p>
              <h2>{result.approvals.length} {result.approvals.length === 1 ? "decision" : "decisions"} awaiting review</h2>
            </div>
            <span className={`review-live-state ${result.approvals.length ? "is-pending" : "is-clear"}`}>
              {result.approvals.length ? "Operator action required" : "No active approvals"}
            </span>
          </div>
          <HumanReviewQueue approvals={result.approvals} unavailable={result.unavailable} />
        </section>

        <ExpiredReviewRecords
          approvals={result.expiredApprovals}
          unavailable={result.unavailable}
        />
      </main>
    </div>
  );
}
