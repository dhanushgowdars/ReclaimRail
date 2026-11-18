"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ReviewDecisionControls({ approvalId, expectedVersion }: { approvalId: string; expectedVersion: number }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  async function decide(decision: "approve" | "reject") {
    setState("working"); setMessage("");
    try {
      const response = await fetch(`/api/recovery/approvals/${approvalId}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, reviewer_id: "merchant-reviewer", reason, expected_version: expectedVersion }) });
      const body = (await response.json()) as { detail?: string; disposition?: string };
      if (!response.ok) throw new Error(body.detail ?? "The review decision was not accepted");
      setState("done"); setMessage(`Decision recorded: ${body.disposition ?? decision}. The queue is refreshing from the persisted audit record.`); router.refresh();
    } catch (error) { setState("error"); setMessage(error instanceof Error ? error.message : "The review decision could not be recorded"); }
  }
  return <div className="review-decision-controls"><p>This protected reviewer session records a reason with every decision. Approval returns the exact persisted action to the worker; rejection closes this recovery attempt without provider execution.</p><label>Decision reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="What evidence supports this decision?" /></label><div><button disabled={state === "working" || reason.trim().length < 3} onClick={() => decide("approve")}>Approve recorded action</button><button className="is-secondary" disabled={state === "working" || reason.trim().length < 3} onClick={() => decide("reject")}>Reject and close attempt</button></div>{state !== "idle" ? <p className={`review-decision-controls__${state}`}>{message}</p> : null}</div>;
}
