import { LoaderCircle } from "lucide-react";

export default function Loading() {
  return (
    <main className="system-state" aria-live="polite" aria-busy="true">
      <LoaderCircle className="system-state__spinner" size={30} />
      <p className="kicker">Refreshing persisted evidence</p>
      <h1>Loading recovery operations</h1>
      <p>ReclaimRail is reading the latest case, policy, provider, and outcome records.</p>
    </main>
  );
}
