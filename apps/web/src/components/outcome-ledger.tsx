"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, CheckCircle2, Clock3, Search, ShieldCheck } from "lucide-react";

import { type RecoveryOutcome } from "@/lib/recovery-api";
import { formatMoney, formatTimestamp } from "@/lib/presentation";

type EvidenceState = "all" | "recovered" | "pending" | "protected";

function stateOf(outcome: RecoveryOutcome): Exclude<EvidenceState, "all"> {
  const netRecovered = outcome.gross_recovered_minor - outcome.reversed_minor;
  if (
    outcome.status === "duplicate_collection_prevented" ||
    outcome.duplicate_collection_prevented_minor > 0
  ) {
    return "protected";
  }
  return outcome.status === "recovered" || netRecovered > 0 ? "recovered" : "pending";
}

function stateCopy(state: Exclude<EvidenceState, "all">) {
  if (state === "recovered") {
    return {
      label: "Provider confirmed",
      detail: "Payment and reconciliation evidence recorded",
      background: "#e8f8f1",
      color: "#087a55",
      border: "#9ee5c8",
    };
  }
  if (state === "protected") {
    return {
      label: "Stopped safely",
      detail: "Unsafe collection was stopped by policy",
      background: "#fff3df",
      color: "#a85300",
      border: "#f7cf91",
    };
  }
  return {
    label: "Awaiting proof",
    detail: "Recovery action recorded; provider result is pending",
    background: "#eef4ff",
    color: "#235ea8",
    border: "#b8d4ff",
  };
}

export function OutcomeLedger({ outcomes, currency }: { outcomes: RecoveryOutcome[]; currency: string }) {
  const [stateFilter, setStateFilter] = useState<EvidenceState>("all");
  const [query, setQuery] = useState("");

  const recovered = useMemo(
    () => outcomes.filter((outcome) => stateOf(outcome) === "recovered"),
    [outcomes],
  );
  const pending = useMemo(
    () => outcomes.filter((outcome) => stateOf(outcome) === "pending"),
    [outcomes],
  );
  const protectedOutcomes = useMemo(
    () => outcomes.filter((outcome) => stateOf(outcome) === "protected"),
    [outcomes],
  );

  const recoveredValue = recovered.reduce(
    (total, outcome) => total + Math.max(0, outcome.gross_recovered_minor - outcome.reversed_minor),
    0,
  );
  const pendingValue = pending.reduce(
    (total, outcome) => total + Math.max(0, outcome.original_amount_minor),
    0,
  );
  const protectedValue = protectedOutcomes.reduce(
    (total, outcome) => total + Math.max(0, outcome.duplicate_collection_prevented_minor),
    0,
  );
  const conversionBase = recovered.length + pending.length + protectedOutcomes.length;
  const conversion = conversionBase === 0
    ? null
    : (recovered.length / conversionBase) * 100;

  const dailyRecovery = recovered.reduce<Record<string, { amount: number; cases: number; label: string }>>(
    (result, outcome) => {
      const date = new Date(outcome.occurred_at);
      const key = date.toISOString().slice(0, 10);
      const current = result[key] ?? {
        amount: 0,
        cases: 0,
        label: date.toLocaleDateString("en-IN", { day: "numeric", month: "short" }),
      };
      result[key] = {
        ...current,
        amount: current.amount + Math.max(0, outcome.gross_recovered_minor - outcome.reversed_minor),
        cases: current.cases + 1,
      };
      return result;
    },
    {},
  );
  const bars = Object.entries(dailyRecovery).sort(([first], [second]) => first.localeCompare(second)).slice(-6);
  const largestBar = Math.max(...bars.map(([, value]) => value.amount), 1);

  const shown = outcomes.filter((outcome) => {
    const matchesState = stateFilter === "all" || stateOf(outcome) === stateFilter;
    const haystack = [
      outcome.recovery_case_id,
      outcome.status,
      outcome.payment_link_id ?? "",
    ].join(" ").toLowerCase();
    return matchesState && haystack.includes(query.trim().toLowerCase());
  });

  const metrics = [
    {
      label: "Provider-confirmed recovered",
      value: formatMoney(recoveredValue, currency),
      note: `${recovered.length} reconciled provider-confirmed case${recovered.length === 1 ? "" : "s"}`,
      icon: CheckCircle2,
      color: "#087a55",
      background: "#f3fcf7",
      border: "#b7ebd0",
    },
    {
      label: "Pending recovery value",
      value: formatMoney(pendingValue, currency),
      note: `${pending.length} awaiting provider proof - not revenue`,
      icon: Clock3,
      color: "#9a5d00",
      background: "#fffaf0",
      border: "#f8d9a0",
    },
    ...(protectedOutcomes.length > 0
      ? [{
          label: "Safely stopped value",
          value: formatMoney(protectedValue, currency),
          note: `${protectedOutcomes.length} duplicate-risk case${protectedOutcomes.length === 1 ? "" : "s"} prevented`,
          icon: ShieldCheck,
          color: "#9b4d00",
          background: "#fff7ed",
          border: "#fed7aa",
        }]
      : []),
    {
      label: "Provider-confirmed recovery rate",
      value: conversion === null ? "â€”" : `${conversion.toFixed(1)}%`,
      note: conversionBase === 0 ? "No recovery outcomes yet" : `${recovered.length} of ${conversionBase} recovery outcomes are provider-confirmed`,
      icon: CheckCircle2,
      color: "#1d5eb6",
      background: "#f4f8ff",
      border: "#bfd7ff",
    },
  ];

  return (
    <div className="outcome-ledger" style={{ width: "100%", maxWidth: "none" }}>
      <section
        aria-label="Recovery outcome summary"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${metrics.length}, minmax(0, 1fr))`,
          width: "100%",
          gap: 14,
          marginBottom: 22,
        }}
      >
        {metrics.map((metric) => {
          const Icon = metric.icon;
          return (
            <article
              key={metric.label}
              style={{
                minHeight: 150,
                padding: 20,
                border: `1px solid ${metric.border}`,
                borderRadius: 14,
                background: metric.background,
                display: "grid",
                alignContent: "space-between",
              }}
            >
              <Icon size={22} color={metric.color} strokeWidth={2.2} />
              <div>
                <p style={{ margin: "10px 0 6px", color: "#48627d", fontSize: 14, fontWeight: 750 }}>{metric.label}</p>
                <strong style={{ color: "#082f5c", fontSize: 29, letterSpacing: "-0.035em" }}>{metric.value}</strong>
                <p style={{ margin: "8px 0 0", color: "#526b85", fontSize: 13, lineHeight: 1.35, fontWeight: 650 }}>{metric.note}</p>
              </div>
            </article>
          );
        })}
      </section>

      <section
        aria-label="Verified recovered amount by date"
        style={{ width: "100%", padding: 22, border: "1px solid #d8e5f4", borderRadius: 14, background: "#fff", marginBottom: 20 }}
      >
        <div style={{ display: "flex", alignItems: "start", justifyContent: "space-between", gap: 16, marginBottom: 18 }}>
          <div>
            <p className="kicker">Recovered revenue</p>
            <h3 style={{ margin: "0 0 7px", fontSize: 23 }}>Verified recovered amount by date</h3>
            <p style={{ margin: 0, color: "#53708c", fontSize: 14, fontWeight: 600 }}>Only provider-confirmed, reconciled payments are included.</p>
          </div>
          <span style={{ padding: "7px 10px", borderRadius: 99, background: "#eef5ff", color: "#275fa8", fontSize: 12, fontWeight: 800, whiteSpace: "nowrap" }}>
            {bars.length} recovery date{bars.length === 1 ? "" : "s"}
          </span>
        </div>

        <p style={{ margin: "0 0 9px", color: "#405e7d", fontSize: 13, fontWeight: 800 }}>Recovered amount (INR)</p>
        <div style={{ minHeight: 224, padding: "14px 18px 0", borderLeft: "1px solid #d8e5f4", borderBottom: "1px solid #d8e5f4", background: "repeating-linear-gradient(to top, transparent 0, transparent 53px, #edf3fa 54px)" }}>
          {bars.length === 0 ? (
            <p style={{ color: "#5f7287", fontSize: 14 }}>No recovered outcomes have been reconciled yet.</p>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${bars.length}, minmax(118px, 150px))`,
                justifyContent: "start",
                alignItems: "end",
                gap: 22,
                height: 206,
              }}
            >
              {bars.map(([date, value]) => (
                <div key={date} title={`${value.label}: ${formatMoney(value.amount, currency)} across ${value.cases} case${value.cases === 1 ? "" : "s"}`} style={{ display: "grid", gridTemplateRows: "auto 1fr auto", alignItems: "end", height: "100%" }}>
                  <strong style={{ display: "block", marginBottom: 8, color: "#082f5c", fontSize: 15, textAlign: "left" }}>{formatMoney(value.amount, currency)}</strong>
                  <div style={{ height: "100%", display: "flex", alignItems: "end" }}>
                    <i style={{ display: "block", width: "100%", height: `${Math.max(16, (value.amount / largestBar) * 100)}%`, borderRadius: "7px 7px 1px 1px", background: "#2563eb" }} />
                  </div>
                  <span style={{ display: "block", paddingTop: 9, color: "#5d738c", fontSize: 13, fontWeight: 700, textAlign: "left" }}>{value.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p style={{ margin: "9px 0 0", color: "#5d738c", fontSize: 13, fontWeight: 700 }}>Recovery date</p>
      </section>

      <section aria-label="Outcome evidence">
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 14, marginBottom: 16 }}>
          <div className="outcome-ledger__filters" style={{ margin: 0 }}>
            {([
              ["all", "All evidence"],
              ["recovered", "Recovered"],
              ["pending", `Pending (${pending.length})`],
              ["protected", `Stopped safely (${protectedOutcomes.length})`],
            ] as const).map(([value, label]) => (
              <button className={stateFilter === value ? "is-active" : ""} key={value} onClick={() => setStateFilter(value)}>{label}</button>
            ))}
          </div>
          <label style={{ position: "relative", display: "block", minWidth: 290 }}>
            <Search size={17} style={{ position: "absolute", left: 12, top: 12, color: "#627991" }} />
            <input
              aria-label="Search cases"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search case ID or outcome"
              style={{ width: "100%", minHeight: 42, padding: "0 12px 0 37px", border: "1px solid #c9d9ea", borderRadius: 9, background: "#fff", color: "#102f50", fontSize: 14, outline: "none" }}
            />
          </label>
        </div>

        <div style={{ display: "flex", alignItems: "end", justifyContent: "space-between", marginBottom: 10 }}>
          <div>
            <p className="kicker">Recovery proof</p>
            <h3 style={{ margin: 0, fontSize: 22 }}>{stateFilter === "all" ? "All outcome evidence" : stateFilter === "recovered" ? "Provider-confirmed recoveries" : stateFilter === "pending" ? "Pending provider outcomes" : "Safety-stopped recovery attempts"}</h3>
          </div>
          <span style={{ color: "#52708c", fontSize: 13, fontWeight: 800 }}>{shown.length} record{shown.length === 1 ? "" : "s"}</span>
        </div>

        <div style={{ overflowX: "auto", border: "1px solid #d8e5f4", borderRadius: 12, background: "#fff" }}>
          <div style={{ minWidth: 940, display: "grid", gridTemplateColumns: "1.35fr 1.1fr 1.45fr 1fr 1fr 1.1fr", gap: 16, padding: "13px 18px", borderBottom: "1px solid #d8e5f4", color: "#58718c", fontSize: 12, fontWeight: 850, textTransform: "uppercase", letterSpacing: ".055em" }}>
            <span>Case / original amount</span><span>Recovery action</span><span>Provider outcome</span><span>Reconciled at</span><span>Value</span><span>Evidence</span>
          </div>
          {shown.length === 0 ? (
            <p style={{ padding: 20, margin: 0, color: "#5f7287" }}>No cases match this evidence view.</p>
          ) : shown.map((outcome) => {
            const state = stateOf(outcome);
            const presentation = stateCopy(state);
            const value = state === "recovered"
              ? Math.max(0, outcome.gross_recovered_minor - outcome.reversed_minor)
              : state === "protected"
                ? Math.max(0, outcome.duplicate_collection_prevented_minor)
                : Math.max(0, outcome.original_amount_minor);
            return (
              <Link
                href={`/cases/${outcome.recovery_case_id}`}
                key={outcome.recovery_outcome_id}
                style={{ minWidth: 940, display: "grid", gridTemplateColumns: "1.35fr 1.1fr 1.45fr 1fr 1fr 1.1fr", alignItems: "center", gap: 16, padding: "16px 18px", borderBottom: "1px solid #e4edf7", color: "inherit", textDecoration: "none" }}
              >
                <span><strong style={{ display: "block", color: "#082f5c", fontSize: 14 }}>CASE-{outcome.recovery_case_id.slice(-8).toUpperCase()}</strong><small style={{ display: "block", marginTop: 5, color: "#5d738c", fontSize: 13 }}>{formatMoney(outcome.original_amount_minor, outcome.currency)} original payment</small></span>
                <span style={{ color: "#314f6c", fontSize: 13, fontWeight: 700 }}>{outcome.payment_link_id ? "Razorpay Payment Link" : "No payment link executed"}</span>
                <span><b style={{ display: "inline-block", padding: "5px 8px", border: `1px solid ${presentation.border}`, borderRadius: 99, background: presentation.background, color: presentation.color, fontSize: 12 }}>{presentation.label}</b><small style={{ display: "block", marginTop: 6, color: "#526b85", fontSize: 12, lineHeight: 1.35 }}>{presentation.detail}</small></span>
                <span style={{ color: "#4c6882", fontSize: 13, fontWeight: 650 }}>{state === "recovered" ? formatTimestamp(outcome.updated_at) : "Not reconciled"}</span>
                <span><strong style={{ display: "block", color: "#082f5c", fontSize: 15 }}>{formatMoney(value, outcome.currency)}</strong><small style={{ color: "#5d738c", fontSize: 12 }}>{state === "recovered" ? "Recovered" : state === "protected" ? "Duplicate risk avoided" : "Not revenue"}</small></span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "#1e63c6", fontSize: 13, fontWeight: 800 }}>Open proof <ArrowUpRight size={15} /></span>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}


