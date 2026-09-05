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
    helper: "Inspect the recorded planner recommendation and the deterministic safety decision.",
    next: "Only an allowed action can move to Razorpay execution.",
  },
  {
    id: "provider",
    label: "Provider action",
    icon: Link2,
    helper: "See the exact bounded action recorded by Razorpay.",
    next: "Only an executed provider action can produce a payment outcome for Razorpay to confirm.",
  },
  {
    id: "outcome",
    label: "Outcome & audit",
    icon: Banknote,
    helper: "Confirm the financial result and inspect the evidence chain.",
    next: "Provider evidence proves financial outcomes; policy or reviewer evidence can close execution safely.",
  },
] as const;

type TabId = (typeof tabs)[number]["id"];

function guideFor(
  tabId: TabId,
  caseStatus: string,
  outcomeStatus: string | null,
  providerStatus: string | null,
): { helper: string; resultLabel: string; result: string } {
  const tab = tabs.find((candidate) => candidate.id === tabId) ?? tabs[0];
  const recovered = caseStatus === "recovered" || outcomeStatus === "recovered";
  if (!recovered) {
    return { helper: tab.helper, resultLabel: "What happens next", result: tab.next };
  }
  const completed: Record<TabId, string> = {
    lifecycle: "Original payment failure was verified before recovery began.",
    decision: "The recorded planner proposed the action and deterministic policy recorded its verdict.",
    provider: providerStatus === "paid"
      ? "Razorpay reports the bounded recovery link as paid."
      : "The bounded Razorpay action has completed.",
    outcome: "Razorpay confirmed the recovered payment and the case was closed.",
  };
  return { helper: tab.helper, resultLabel: "Recorded result", result: completed[tabId] };
}

export function CaseEvidenceTabs({
  lifecycle,
  decision,
  provider,
  outcome,
  caseStatus,
  outcomeStatus,
  providerStatus,
}: {
  lifecycle: ReactNode;
  decision: ReactNode;
  provider: ReactNode;
  outcome: ReactNode;
  caseStatus: string;
  outcomeStatus: string | null;
  providerStatus: string | null;
}) {
  const [activeTab, setActiveTab] = useState<TabId>(
    caseStatus === "recovered" || outcomeStatus === "recovered" ? "outcome" : "lifecycle",
  );
  const content = { lifecycle, decision, provider, outcome };
  const guide = guideFor(activeTab, caseStatus, outcomeStatus, providerStatus);

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
          <p>{guide.helper}</p>
          <p><b>{guide.resultLabel}:</b> {guide.result}</p>
        </div>
        {content[activeTab]}
      </div>
    </section>
  );
}
