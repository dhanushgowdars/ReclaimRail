import { OperationsPage } from "@/components/operations-page";
import { loadRecoveryDashboard } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function ReviewsPage() {
  const data = await loadRecoveryDashboard();
  return <OperationsPage section="reviews" summary={data.summary} cases={data.cases.items} outcomes={data.outcomes.items} incidents={data.incidents} />;
}
