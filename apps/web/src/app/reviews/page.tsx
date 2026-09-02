import { HumanReviewQueue } from "@/components/human-review-queue";
import { RecoveryNavigation } from "@/components/recovery-navigation";
import { loadRecoveryApprovals } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function ReviewsPage() {
  const result = await loadRecoveryApprovals().then((approvals) => ({ approvals, unavailable: false })).catch(() => ({ approvals: [], unavailable: true }));
  return <div className="app-shell"><RecoveryNavigation active="reviews" /><main className="workspace operations-page"><header className="operations-page__hero"><p className="kicker">Protected automation</p><h1>Human review queue</h1><p>High-value actions stop here until a reviewer records an evidence-backed decision. ReclaimRail never turns an approval boundary into silent automation.</p><span className="test-mode"><i /> Razorpay Test Mode · protected operator action</span></header><section className="panel"><div className="panel-heading"><div><p className="kicker">Pending approval evidence</p><h2>{result.approvals.length} decisions awaiting review</h2></div></div><HumanReviewQueue approvals={result.approvals} unavailable={result.unavailable} /></section></main></div>;
}
