import { CommandCenter } from "@/components/command-center";
import { loadRecoveryDashboard } from "@/lib/recovery-api";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const data = await loadRecoveryDashboard(100);
  return <CommandCenter summary={data.summary} cases={data.cases.items} />;
}
