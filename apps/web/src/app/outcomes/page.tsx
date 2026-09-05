import { OperationsPage } from "@/components/operations-page";
import { loadRecoveryDashboard, loadRecoveryOutcomeHistory } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function OutcomesPage() {
  const [data, outcomes] = await Promise.all([
    loadRecoveryDashboard(),
    loadRecoveryOutcomeHistory(),
  ]);
  return <OperationsPage section="outcomes" summary={data.summary} cases={data.cases.items} outcomes={outcomes} incidents={data.incidents} />;
}

