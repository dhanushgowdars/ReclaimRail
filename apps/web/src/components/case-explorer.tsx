"use client";

import { Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { type RecoveryCaseQueueItem } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp, shortId, titleCase } from "@/lib/presentation";

export function CaseExplorer({ cases, currency }: { cases: RecoveryCaseQueueItem[]; currency: string }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [rail, setRail] = useState("all");
  const rails = [...new Set(cases.map((item) => item.payment_method).filter((value): value is string => value !== null))];
  const shown = cases.filter((item) => {
    const haystack = `${item.recovery_case_id} ${item.status} ${item.payment_method ?? ""} ${item.latest_action_policy_outcome ?? ""}`.toLowerCase();
    return haystack.includes(query.toLowerCase()) && (status === "all" || item.status === status) && (rail === "all" || item.payment_method === rail);
  });
  return <div className="case-explorer"><div className="case-explorer__controls"><label><Search size={17} /><span className="sr-only">Search recovery cases</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search case ID, rail, or status" /></label><label><SlidersHorizontal size={17} /><span className="sr-only">Filter by status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option>{[...new Set(cases.map((item) => item.status))].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label><label><span className="sr-only">Filter by payment rail</span><select value={rail} onChange={(event) => setRail(event.target.value)}><option value="all">All payment rails</option>{rails.map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select></label></div><p className="case-explorer__count">{shown.length} of {cases.length} cases shown</p><div className="operations-list">{shown.length === 0 ? <p className="detail-empty">No cases match these filters.</p> : shown.map((item) => <Link key={item.recovery_case_id} href={`/cases/${item.recovery_case_id}`} className="operations-list__row"><div><strong>CASE-{shortId(item.recovery_case_id)}</strong><span>{item.payment_method === null ? "Payment rail pending" : titleCase(item.payment_method)} · opened {formatTimestamp(item.opened_at)}</span></div><div><span className="badge badge--neutral">{titleCase(item.status)}</span><span>{item.latest_action_type === null ? "Awaiting plan" : titleCase(item.latest_action_type)}</span></div><strong>{formatMoney(item.amount_minor, currency)}</strong><span>Open evidence</span></Link>)}</div></div>;
}
