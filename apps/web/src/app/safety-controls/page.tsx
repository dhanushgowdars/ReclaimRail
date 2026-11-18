import { OperationsPage } from "@/components/operations-page";
import { loadRecoveryDashboard, loadWorkerFleetHealth } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function SafetyControlsPage() {
  const [data, workerHealth] = await Promise.all([
    loadRecoveryDashboard(100),
    loadWorkerFleetHealth().catch(() => null),
  ]);
  return <OperationsPage section="controls" summary={data.summary} cases={data.cases.items} outcomes={data.outcomes.items} incidents={data.incidents} workerHealth={workerHealth} />;
}
