"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="system-state system-state--error" role="alert">
      <AlertTriangle size={31} />
      <p className="kicker">Operational data unavailable</p>
      <h1>ReclaimRail could not load current evidence</h1>
      <p>No outcome has been changed or inferred. Check that the local API and workers are running, then retry this view.</p>
      <button type="button" onClick={reset}><RefreshCw size={17} /> Retry loading evidence</button>
    </main>
  );
}
