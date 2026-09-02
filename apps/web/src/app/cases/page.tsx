import { OperationsPage } from "@/components/operations-page";
import { loadRecoveryDashboard } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function CasesPage() {
  const data = await loadRecoveryDashboard(100);
  return <OperationsPage section="queue" summary={data.summary} cases={data.cases.items} outcomes={data.outcomes.items} incidents={data.incidents} />;
}
