"use client";

import { Banknote, BrainCircuit, CreditCard, Link2 } from "lucide-react";
import { useState, type ReactNode } from "react";

const tabs = [
  {
    id: "lifecycle",
    label: "Lifecycle",
    icon: CreditCard,
    helper: "Verify the payment state and the signed failure evidence.",
    next: "Review the agent recommendation once the failure is eligible.",
  },
  {
    id: "decision",
    label: "Agent & policy",
    icon: BrainCircuit,
    helper: "Inspect Gemini's recommendation and the deterministic safety decision.",
    next: "Only an allowed action can move to Razorpay execution.",
  },
  {
    id: "provider",
    label: "Provider action",
    icon: Link2,
    helper: "See the exact bounded action recorded by Razorpay.",
    next: "Wait for provider evidence before treating a payment as recovered.",
  },
  {
    id: "outcome",
    label: "Outcome & audit",
    icon: Banknote,
    helper: "Confirm the financial result and inspect the evidence chain.",
    next: "Recovered revenue changes only after provider reconciliation.",
  },
] as const;

type TabId = (typeof tabs)[number]["id"];

export function CaseEvidenceTabs({
  lifecycle,
  decision,
  provider,
  outcome,
}: {
  lifecycle: ReactNode;
  decision: ReactNode;
  provider: ReactNode;
  outcome: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<TabId>("lifecycle");
  const content = { lifecycle, decision, provider, outcome };

  return (
    <section className="case-tabs">
      <div className="case-tabs__heading">
        <p className="kicker">Recovery evidence</p>
        <h2>Follow the case in business order</h2>
      </div>
      <div className="case-tabs__list" role="tablist" aria-label="Recovery case evidence">
        {tabs.map((tab, index) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.id;
          return (
            <button
              aria-controls={`case-panel-${tab.id}`}
              aria-selected={selected}
              className={selected ? "is-active" : ""}
              id={`case-tab-${tab.id}`}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              role="tab"
              type="button"
            >
              <span>{index + 1}</span>
              <Icon size={18} />
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        aria-labelledby={`case-tab-${activeTab}`}
        className="case-tabs__panel"
        id={`case-panel-${activeTab}`}
        role="tabpanel"
      >
        <div className="case-tabs__guide" aria-live="polite">
          <div>
            <span>Current review step</span>
            <strong>{tabs.find((tab) => tab.id === activeTab)?.label}</strong>
          </div>
          <p>{tabs.find((tab) => tab.id === activeTab)?.helper}</p>
          <p><b>What happens next:</b> {tabs.find((tab) => tab.id === activeTab)?.next}</p>
        </div>
        {content[activeTab]}
      </div>
    </section>
  );
}
