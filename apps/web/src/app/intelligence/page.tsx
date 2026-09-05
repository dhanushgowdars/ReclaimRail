import { RecoveryBrainDashboard } from "@/components/recovery-brain-dashboard";
import { loadRecoveryCaseDetail, loadRecoveryDashboard } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function IntelligencePage() {
  const data = await loadRecoveryDashboard(25);
  const selectedCase = [...data.cases.items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const detail = selectedCase ? await loadRecoveryCaseDetail(selectedCase.recovery_case_id).catch(() => null) : null;
  return <RecoveryBrainDashboard detail={detail} cases={data.cases.items} incidents={data.incidents} />;
}
