"use client";

import { ArrowUpRight, CalendarDays, CreditCard, RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { type RecoveryCaseQueueItem } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

type CaseTone = "open" | "review" | "closed" | "recovered" | "waiting";
function caseTone(item: RecoveryCaseQueueItem): CaseTone {
  if (item.outcome_status === "recovered" || item.status === "recovered") return "recovered";
  if (item.latest_approval_status === "pending") return "review";
  if (["rejected", "expired"].includes(item.latest_approval_status ?? "")) return "closed";
  if (["blocked", "stopped", "cancelled", "exhausted"].includes(item.status) || item.latest_action_policy_outcome === "block") return "closed";
  if (item.outcome_status === "payment_link_pending" || (item.latest_action_status === "succeeded" && item.outcome_status !== "recovered")) return "waiting";
  return "open";
}
function statusLabel(tone: CaseTone): string { return { open: "Open", review: "Human review", closed: "Closed", recovered: "Recovered", waiting: "Awaiting Razorpay" }[tone]; }
function statusCopy(tone: CaseTone, item: RecoveryCaseQueueItem): string {
  if (tone === "review") return item.latest_approval_reason === null ? "Protected decision pending" : `${titleCase(item.latest_approval_reason)} · decision pending`;
  if (item.latest_approval_status === "rejected") return item.latest_approval_decision_reason === null ? "Review rejected · no provider execution" : `Review rejected: ${item.latest_approval_decision_reason}`;
  if (item.latest_approval_status === "expired") return "Approval expired · no provider execution";
  if (tone === "closed") return item.latest_action_policy_outcome === "block" ? "Blocked by recorded policy decision" : "Recovery workflow closed";
  if (tone === "recovered") return "Razorpay confirmed recovery payment";
  if (tone === "waiting") return item.latest_approval_status === "approved" ? "Reviewer approved · awaiting Razorpay outcome" : item.outcome_status === "payment_link_pending" ? "Payment link awaiting Razorpay outcome" : "Waiting for recorded evidence";
  if (item.latest_approval_status === "approved") return item.latest_approval_decision_reason === null ? "Reviewed action approved" : `Approved: ${item.latest_approval_decision_reason}`;
  return item.latest_action_type === null ? "Waiting for a recorded recovery plan" : `${titleCase(item.latest_action_type)} · ${titleCase(item.status)}`;
}

export function CaseExplorer({ cases, currency }: { cases: RecoveryCaseQueueItem[]; currency: string }) {
  const [query, setQuery] = useState(""); const [status, setStatus] = useState("all"); const [rail, setRail] = useState("all"); const [sortBy, setSortBy] = useState("newest");
  const rails = ["netbanking", "wallet", "card", "upi"];
  const shown = cases.filter((item) => { const haystack = `${item.recovery_case_id} ${item.status} ${item.payment_method ?? ""} ${item.latest_action_policy_outcome ?? ""}`.toLowerCase(); return haystack.includes(query.toLowerCase()) && (status === "all" || caseTone(item) === status) && (rail === "all" || item.payment_method === rail); }).sort((left, right) => { if (sortBy === "oldest") return new Date(left.opened_at).getTime() - new Date(right.opened_at).getTime(); if (sortBy === "amount-high") return right.amount_minor - left.amount_minor; if (sortBy === "amount-low") return left.amount_minor - right.amount_minor; return new Date(right.opened_at).getTime() - new Date(left.opened_at).getTime(); });
  const filtersActive = query !== "" || status !== "all" || rail !== "all" || sortBy !== "newest";
  const stateFilters = [["all", "All cases"], ["review", "Human review"], ["waiting", "Awaiting Razorpay"], ["recovered", "Recovered"], ["closed", "Closed"]] as const;
  return <div className="case-explorer">
    <div className="case-state-guide"><strong>What each state means</strong><span><b>Human review</b> — an unexpired reviewer decision is pending</span><span><b>Awaiting Razorpay</b> — an executed action awaits payment confirmation</span><span><b>Recovered</b> — Razorpay confirmed the recovery payment</span><span><b>Closed</b> — the recorded review expired, was rejected, or policy blocked execution</span></div>
    <div className="case-explorer__controls"><label><Search size={18} /><span className="sr-only">Search recovery cases</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search case ID, rail, or status" /></label><label><SlidersHorizontal size={18} /><span className="sr-only">Filter by business state</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All recorded states</option><option value="review">Human review pending</option><option value="waiting">Awaiting Razorpay</option><option value="recovered">Provider-confirmed recovered</option><option value="closed">Closed without recovery</option></select></label><label><span className="sr-only">Filter by payment rail</span><select value={rail} onChange={(event) => setRail(event.target.value)}><option value="all">All payment rails</option>{rails.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label><label><span className="sr-only">Sort cases</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="amount-high">Amount: high to low</option><option value="amount-low">Amount: low to high</option></select></label></div>
    <div className="case-explorer__summary"><p className="case-explorer__count">{shown.length} of {cases.length} persisted cases shown</p>{filtersActive ? <button type="button" onClick={() => { setQuery(""); setStatus("all"); setRail("all"); setSortBy("newest"); }}><RotateCcw size={14} /> Clear filters</button> : null}</div>
    <div className="case-explorer__legend" aria-label="Filter by recovery state">{stateFilters.map(([value, label]) => <button type="button" key={value} className={`is-${value}${status === value ? " is-active" : ""}`} aria-pressed={status === value} onClick={() => setStatus(value)}>{label}</button>)}</div>
    <div className="case-explorer__list">{shown.length === 0 ? <p className="detail-empty">No cases match these filters.</p> : shown.map((item, index) => { const tone = caseTone(item); const highValue = item.amount_minor >= 1_000_000; return <Link key={item.recovery_case_id} href={`/cases/${item.recovery_case_id}`} className={`case-row case-row--${tone}`}><span className="case-row__number">{String(index + 1).padStart(2, "0")}</span><div className="case-row__identity"><div><strong>CASE-{shortId(item.recovery_case_id)}</strong>{highValue ? <em>₹10,000+ threshold</em> : null}</div><span><CreditCard size={15} />{item.payment_method === null ? "Payment rail pending" : titleCase(item.payment_method)}</span></div><div className="case-row__time"><span><CalendarDays size={15} />Opened</span><strong>{formatTimestamp(item.opened_at)}</strong><small>{item.closed_at === null ? `Last evidence ${formatTimestamp(item.updated_at)}` : `Closed ${formatTimestamp(item.closed_at)}`}</small></div><div className="case-row__state"><span className={`case-status case-status--${tone}`}>{statusLabel(tone)}</span><strong>{statusCopy(tone, item)}</strong></div><div className="case-row__amount"><strong>{formatMoney(item.amount_minor, currency)}</strong><span>{highValue ? "Review threshold amount" : "Original payment amount"}</span></div><span className="case-row__evidence">Open evidence <ArrowUpRight size={16} /></span></Link>; })}</div>
  </div>;
}
