"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { type RecoveryOutcome } from "@/lib/recovery-api";
import { formatMoney, titleCase } from "@/lib/presentation";

type Filter = "all" | "recovered" | "pending" | "protected";

function category(outcome: RecoveryOutcome): Exclude<Filter, "all"> {
  if (outcome.status === "duplicate_collection_prevented") return "protected";
  if (outcome.status === "recovered" || outcome.gross_recovered_minor > outcome.reversed_minor) return "recovered";
  return "pending";
}

export function OutcomeLedger({ outcomes, currency }: { outcomes: RecoveryOutcome[]; currency: string }) {
  const [filter, setFilter] = useState<Filter>("all");
  const totals = useMemo(() => outcomes.reduce((result, outcome) => {
    const key = category(outcome); result[key] += key === "protected" ? outcome.duplicate_collection_prevented_minor : Math.max(0, outcome.gross_recovered_minor - outcome.reversed_minor); return result;
  }, { recovered: 0, pending: 0, protected: 0 }), [outcomes]);
  const shown = outcomes.filter((outcome) => filter === "all" || category(outcome) === filter);
  return <div className="outcome-ledger"><div className="outcome-ledger__metrics"><article><span>Provider-verified recovered</span><strong>{formatMoney(totals.recovered, currency)}</strong></article><article><span>Pending provider outcome</span><strong>{outcomes.filter((item) => category(item) === "pending").length}</strong></article><article><span>Duplicate collection prevented</span><strong>{formatMoney(totals.protected, currency)}</strong></article></div><div className="outcome-ledger__filters">{(["all", "recovered", "pending", "protected"] as const).map((value) => <button className={filter === value ? "is-active" : ""} key={value} onClick={() => setFilter(value)}>{value === "all" ? "All evidence" : value === "protected" ? "Protected" : titleCase(value)}</button>)}</div><div className="operations-list">{shown.length === 0 ? <p className="detail-empty">No outcomes match this evidence state.</p> : shown.map((outcome) => <Link className="operations-list__row" href={`/cases/${outcome.recovery_case_id}`} key={outcome.recovery_outcome_id}><div><strong>{titleCase(outcome.status)}</strong><span>{titleCase(outcome.attribution)} · {outcome.evidence_event_count} provider-linked events</span></div><span className={`badge badge--${category(outcome) === "recovered" ? "success" : category(outcome) === "protected" ? "protected" : "warning"}`}>{category(outcome) === "pending" ? "Awaiting reconciliation" : category(outcome) === "protected" ? "Collection prevented" : "Provider verified"}</span><strong>{formatMoney(Math.max(0, outcome.gross_recovered_minor - outcome.reversed_minor), outcome.currency)}</strong><span>View proof</span></Link>)}</div></div>;
}
