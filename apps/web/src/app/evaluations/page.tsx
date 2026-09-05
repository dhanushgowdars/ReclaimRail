import { EvaluationDashboard } from "@/components/evaluation-dashboard";
import { RecoveryNavigation } from "@/components/recovery-navigation";

export const dynamic = "force-dynamic";

export default function EvaluationsPage() {
  return <div className="app-shell"><RecoveryNavigation active="evaluations" /><EvaluationDashboard /></div>;
}
