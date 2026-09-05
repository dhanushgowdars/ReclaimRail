"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ReviewDecisionControls({ approvalId, expectedVersion }: { approvalId: string; expectedVersion: number }) {
  const router = useRouter();
  const [reviewerCode, setReviewerCode] = useState("");
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  async function decide(decision: "approve" | "reject") {
    setState("working"); setMessage("");
    try {
      const response = await fetch(`/api/recovery/approvals/${approvalId}/decision`, { method: "POST", headers: { "Content-Type": "application/json", "X-ReclaimRail-Reviewer-Code": reviewerCode }, body: JSON.stringify({ decision, reviewer_id: "merchant-reviewer", reason, expected_version: expectedVersion }) });
      const body = (await response.json()) as { detail?: string; disposition?: string };
      if (!response.ok) throw new Error(body.detail ?? "The review decision was not accepted");
      setState("done"); setMessage(`Decision recorded: ${body.disposition ?? decision}. The queue is refreshing from the persisted audit record.`); router.refresh();
    } catch (error) { setState("error"); setMessage(error instanceof Error ? error.message : "The review decision could not be recorded"); }
  }
  return <div className="review-decision-controls"><p>Record a reason before deciding. Approval returns the exact persisted action to the worker; rejection closes this recovery attempt without provider execution.</p><label>Reviewer access code<input value={reviewerCode} onChange={(event) => setReviewerCode(event.target.value)} placeholder="Provided with the demo" autoComplete="off" /></label><label>Decision reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="What evidence supports this decision?" /></label><div><button disabled={state === "working" || reviewerCode.length === 0 || reason.trim().length < 3} onClick={() => decide("approve")}>Approve recorded action</button><button className="is-secondary" disabled={state === "working" || reviewerCode.length === 0 || reason.trim().length < 3} onClick={() => decide("reject")}>Reject and close attempt</button></div>{state !== "idle" ? <p className={`review-decision-controls__${state}`}>{message}</p> : null}</div>;
}
