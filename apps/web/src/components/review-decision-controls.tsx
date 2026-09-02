"use client";

import { useState } from "react";

export function ReviewDecisionControls({ approvalId, expectedVersion }: { approvalId: string; expectedVersion: number }) {
  const [reviewerCode, setReviewerCode] = useState("");
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "working" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  async function decide(decision: "approved" | "declined") {
    setState("working"); setMessage("");
    try {
      const response = await fetch(`/api/recovery/approvals/${approvalId}/decision`, { method: "POST", headers: { "Content-Type": "application/json", "X-ReclaimRail-Reviewer-Code": reviewerCode }, body: JSON.stringify({ decision, reviewer_id: "merchant-reviewer", reason, expected_version: expectedVersion }) });
      const body = (await response.json()) as { detail?: string; disposition?: string };
      if (!response.ok) throw new Error(body.detail ?? "The review decision was not accepted");
      setState("done"); setMessage(`Decision recorded: ${body.disposition ?? decision}. Refresh this page to view the updated queue.`);
    } catch (error) { setState("error"); setMessage(error instanceof Error ? error.message : "The review decision could not be recorded"); }
  }
  return <div className="review-decision-controls"><label>Reviewer access code<input value={reviewerCode} onChange={(event) => setReviewerCode(event.target.value)} placeholder="Provided with the demo" /></label><label>Decision reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain this operator decision" /></label><div><button disabled={state === "working" || reviewerCode.length === 0 || reason.trim().length < 3} onClick={() => decide("approved")}>Approve action</button><button className="is-secondary" disabled={state === "working" || reviewerCode.length === 0 || reason.trim().length < 3} onClick={() => decide("declined")}>Decline action</button></div>{state !== "idle" ? <p className={`review-decision-controls__${state}`}>{message}</p> : null}</div>;
}
