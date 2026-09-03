import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import { ReviewDecisionControls } from "@/components/review-decision-controls";
import { type RecoveryApproval } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId } from "@/lib/presentation";

export function HumanReviewQueue({ approvals, unavailable }: { approvals: RecoveryApproval[]; unavailable: boolean }) {
  if (unavailable) return <p className="detail-empty">Protected review data is unavailable because operator access is not configured for this environment.</p>;
  if (approvals.length === 0) return <div className="review-empty"><ShieldAlert size={25} /><div><strong>No pending human reviews</strong><p>Automation is not bypassing review. Cases appear here only when deterministic policy requires an operator decision.</p></div></div>;
  return <div className="review-queue">{approvals.map((approval) => <article className="review-card" key={approval.approval_id}><div className="review-card__heading"><div><p className="kicker">Protected recovery decision</p><h3>{formatMoney(approval.amount_minor, approval.currency)} requires approval</h3></div><span className="badge badge--warning">Pending review</span></div><p>{approval.request_reason}</p><dl><div><dt>Case evidence</dt><dd><Link href={`/cases/${approval.recovery_case_id}`}>CASE-{shortId(approval.recovery_case_id)}</Link></dd></div><div><dt>Policy threshold</dt><dd>{approval.threshold_minor === null ? "Policy managed" : formatMoney(approval.threshold_minor, approval.currency)}</dd></div><div><dt>Requested</dt><dd>{formatTimestamp(approval.requested_at)}</dd></div><div><dt>Expires</dt><dd>{formatTimestamp(approval.expires_at)}</dd></div></dl><ReviewDecisionControls approvalId={approval.approval_id} expectedVersion={approval.version} /></article>)}</div>;
}
