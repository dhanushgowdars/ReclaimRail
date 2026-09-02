"use client";

import { ArrowUpRight, CalendarDays, CreditCard, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { type RecoveryCaseQueueItem } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

function caseTone(item: RecoveryCaseQueueItem): "ready" | "escalated" | "blocked" | "recovered" | "waiting" {
  if (item.status === "escalated" || item.latest_action_policy_outcome === "escalate") return "escalated";
  if (["blocked", "stopped", "cancelled"].includes(item.status) || item.latest_action_policy_outcome === "block") return "blocked";
  if (item.outcome_status === "recovered" || item.status === "recovered") return "recovered";
  if (item.latest_action_type === null || ["waiting", "executing"].includes(item.status)) return "waiting";
  return "ready";
}

function statusCopy(tone: ReturnType<typeof caseTone>, item: RecoveryCaseQueueItem): string {
  if (tone === "escalated") return "Human review required";
  if (tone === "blocked") return "Policy stopped action";
  if (tone === "recovered") return "Provider reconciliation complete";
  if (tone === "waiting") return "Waiting for next evidence";
  return item.latest_action_type === null ? "Preparing recovery plan" : titleCase(item.latest_action_type);
}

export function CaseExplorer({ cases, currency }: { cases: RecoveryCaseQueueItem[]; currency: string }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [rail, setRail] = useState("all");
  const [sortBy, setSortBy] = useState("newest");
  const rails = [...new Set(cases.map((item) => item.payment_method).filter((value): value is string => value !== null))];
  const shown = cases.filter((item) => {
    const haystack = `${item.recovery_case_id} ${item.status} ${item.payment_method ?? ""} ${item.latest_action_policy_outcome ?? ""}`.toLowerCase();
    return haystack.includes(query.toLowerCase()) && (status === "all" || item.status === status) && (rail === "all" || item.payment_method === rail);
  }).sort((left, right) => {
    if (sortBy === "oldest") return new Date(left.opened_at).getTime() - new Date(right.opened_at).getTime();
    if (sortBy === "amount-high") return right.amount_minor - left.amount_minor;
    if (sortBy === "amount-low") return left.amount_minor - right.amount_minor;
    return new Date(right.opened_at).getTime() - new Date(left.opened_at).getTime();
  });
  return <div className="case-explorer"><div className="case-explorer__controls"><label><Search size={18} /><span className="sr-only">Search recovery cases</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search case ID, rail, or status" /></label><label><SlidersHorizontal size={18} /><span className="sr-only">Filter by status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option>{[...new Set(cases.map((item) => item.status))].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label><label><span className="sr-only">Filter by payment rail</span><select value={rail} onChange={(event) => setRail(event.target.value)}><option value="all">All payment rails</option>{rails.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label><label><span className="sr-only">Sort cases</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="amount-high">Amount: high to low</option><option value="amount-low">Amount: low to high</option></select></label></div><p className="case-explorer__count">{shown.length} of {cases.length} database cases shown</p><div className="case-explorer__list">{shown.length === 0 ? <p className="detail-empty">No cases match these filters.</p> : shown.map((item, index) => { const tone = caseTone(item); const highValue = item.amount_minor >= 1_000_000; return <Link key={item.recovery_case_id} href={`/cases/${item.recovery_case_id}`} className={`case-row case-row--${tone}`}><span className="case-row__number">{String(index + 1).padStart(2, "0")}</span><div className="case-row__identity"><div><strong>CASE-{shortId(item.recovery_case_id)}</strong>{highValue ? <em>High value</em> : null}</div><span><CreditCard size={15} />{item.payment_method === null ? "Payment rail pending" : titleCase(item.payment_method)}</span></div><div className="case-row__time"><span><CalendarDays size={15} />Opened</span><strong>{formatTimestamp(item.opened_at)}</strong></div><div className="case-row__state"><span className={`case-status case-status--${tone}`}>{titleCase(item.status)}</span><strong>{statusCopy(tone, item)}</strong></div><div className="case-row__amount"><strong>{formatMoney(item.amount_minor, currency)}</strong><span>{highValue ? "Protected threshold" : "Amount under control"}</span></div><span className="case-row__evidence">Open evidence <ArrowUpRight size={16} /></span></Link>; })}</div></div>;
}
