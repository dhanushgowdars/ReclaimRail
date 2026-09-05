import { Clock3, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { ReviewDecisionControls } from "@/components/review-decision-controls";
import { ReviewDecisionCountdown } from "@/components/live-time";
import { type RecoveryApproval } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

const reviewReasonLabels: Record<string, string> = {
  amount_threshold: "Amount meets the protected approval threshold",
  active_incident_uncertainty: "An active payment-rail incident adds uncertainty",
  near_maximum_attempts: "This case is near its maximum recovery attempts",
  partial_recovery: "The provider evidence indicates a partial recovery",
  provider_state_conflict: "Provider evidence conflicts with the current payment state",
  policy_requires_review: "A deterministic policy rule explicitly requires review",
};

function ReviewTrigger({ approval }: { approval: RecoveryApproval }) {
  const reasonCodes = Array.isArray(approval.request_context.reason_codes)
    ? approval.request_context.reason_codes.filter((value): value is string => typeof value === "string")
    : [approval.request_reason];
  const attempts = approval.request_context.recovery_attempt_count;
  const maximumAttempts = approval.request_context.maximum_recovery_attempts;
  const incidentSeverity = approval.request_context.active_incident_severity;
  return <section className="review-card__trigger"><p className="kicker">Why this stopped for a person</p><ul>{reasonCodes.map((reason) => <li key={reason}>{reviewReasonLabels[reason] ?? titleCase(reason)}</li>)}</ul><div className="review-card__facts">{typeof attempts === "number" && typeof maximumAttempts === "number" ? <span>Recovery attempts: {attempts} of {maximumAttempts}</span> : null}{typeof incidentSeverity === "string" ? <span>Active incident: {titleCase(incidentSeverity)}</span> : null}</div></section>;
}

export function HumanReviewQueue({ approvals, unavailable }: { approvals: RecoveryApproval[]; unavailable: boolean }) {
  if (unavailable) return <p className="detail-empty">Protected review data is unavailable because operator access is not configured for this environment.</p>;
  return approvals.length === 0 ? <div className="review-empty"><ShieldAlert size={25} /><div><strong>No threshold-protected action is waiting</strong><p>This is a healthy live state. A permitted payment-link action of ₹10,000 or more will appear here and update the Command Center from the same database record.</p></div></div> : <div className="review-queue">{approvals.map((approval, index) => <article className="review-card" key={approval.approval_id}><div className="review-card__heading"><div><p className="kicker">Review {String(index + 1).padStart(2, "0")} of {String(approvals.length).padStart(2, "0")} · protected recovery decision</p><h3>{formatMoney(approval.amount_minor, approval.currency)} is paused for review</h3></div><span className="badge badge--warning">Pending review</span></div><p>An approval releases only this recorded action. It cannot override a failed policy check, change the amount or currency, or bypass provider evidence.</p><ReviewTrigger approval={approval} /><dl><div><dt>Case evidence</dt><dd><Link href={`/cases/${approval.recovery_case_id}`}>CASE-{shortId(approval.recovery_case_id)}</Link></dd></div><div><dt>Action</dt><dd>Recovery payment link</dd></div><div><dt>Protected threshold</dt><dd>{formatMoney(approval.threshold_minor ?? 1_000_000, approval.currency)}</dd></div><div><dt>Decision deadline</dt><dd>{formatTimestamp(approval.expires_at)}<small className="review-card__countdown"><ReviewDecisionCountdown expiresAt={approval.expires_at} /></small></dd></div></dl><ReviewDecisionControls approvalId={approval.approval_id} expectedVersion={approval.version} /></article>)}</div>;
}

export function ExpiredReviewRecords({
  approvals,
  unavailable,
}: {
  approvals: RecoveryApproval[];
  unavailable: boolean;
}) {
  if (unavailable || approvals.length === 0) return null;
  const recentApprovals = approvals.slice(0, 12);

  return (
    <section className="panel review-expired" aria-label="Expired approvals without a decision">
      <div className="panel-heading">
        <div>
          <p className="kicker">Closed automatically</p>
          <h2>Expired without a decision</h2>
        </div>
        <span className="review-expired__count">{approvals.length} recorded</span>
      </div>
      <p className="review-expired__intro">
        These protected actions received no approval or rejection before their deadline.
        They are not actionable now: no provider execution was authorised, and each case
        remains available as read-only evidence.
      </p>
      <div className="review-expired__list">
        {recentApprovals.map((approval, index) => (
          <article key={approval.approval_id}>
            <span className="review-expired__number">{String(index + 1).padStart(2, "0")}</span>
            <Clock3 size={19} />
            <div>
              <strong>{formatMoney(approval.amount_minor, approval.currency)} · approval window expired</strong>
              <small>{approval.decision_reason ?? "No reviewer decision was recorded before expiry."}</small>
            </div>
            <dl>
              <div><dt>Case evidence</dt><dd><Link href={`/cases/${approval.recovery_case_id}`}>CASE-{shortId(approval.recovery_case_id)}</Link></dd></div>
              <div><dt>Expired</dt><dd>{formatTimestamp(approval.expires_at)}</dd></div>
            </dl>
          </article>
        ))}
      </div>
      {approvals.length > recentApprovals.length ? <p className="review-expired__more">Showing the {recentApprovals.length} most recent expired approvals.</p> : null}
    </section>
  );
}
