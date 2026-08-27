"use client";

import {
  ArrowRight,
  Banknote,
  BrainCircuit,
  Check,
  CircleDot,
  ClipboardCheck,
  Clock3,
  Copy,
  CreditCard,
  ExternalLink,
  Link2,
  LoaderCircle,
  Play,
  RotateCcw,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import Script from "next/script";
import { useEffect, useRef, useState } from "react";

import { LiveElapsed } from "@/components/live-time";
import {
  type PaymentLabLiveRun,
  usePaymentLabLiveRun,
} from "@/hooks/use-payment-lab-live-run";
import { formatMoney, formatTimestamp } from "@/lib/presentation";

type PaymentLabMode = "guided" | "custom";
type PaymentMethod = "upi" | "card" | "netbanking" | "wallet";
type RunState =
  | "idle"
  | "creating_order"
  | "opening_checkout"
  | "awaiting_webhook"
  | "browser_success"
  | "dismissed"
  | "error";

type PaymentLabResponse = {
  payment_lab_run_id: string;
  client_request_id: string;
  mode: PaymentLabMode;
  provenance: "razorpay_test";
  status: "checkout_ready";
  test_mode: true;
  checkout_expires_at: string;
  checkout: {
    key_id: string;
    order_id: string;
    amount_minor: number;
    currency: string;
    name: string;
    description: string;
    timeout_seconds: number;
    theme_color: string;
    payment_method_hint: PaymentMethod;
  };
};

type RazorpaySuccess = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};

type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  timeout: number;
  theme: { color: string };
  retry: { enabled: boolean };
  modal: { ondismiss: () => void; confirm_close: boolean };
  handler: (response: RazorpaySuccess) => void;
};

type RazorpayInstance = {
  open: () => void;
  on: (event: "payment.failed", handler: () => void) => void;
};

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

type LiveStepStatus = "pending" | "active" | "completed" | "failed";

function stepStatusLabel(status: LiveStepStatus): string {
  if (status === "completed") return "Verified";
  if (status === "active") return "Live";
  if (status === "failed") return "Stopped";
  return "Waiting";
}

function stateCopy(state: RunState): { title: string; detail: string } {
  const copy: Record<RunState, { title: string; detail: string }> = {
    idle: {
      title: "Ready for a provider-live run",
      detail: "No order has been created yet.",
    },
    creating_order: {
      title: "Creating a bounded Test Mode Order",
      detail: "The server is authenticating with Razorpay. Secrets remain server-side.",
    },
    opening_checkout: {
      title: "Razorpay Checkout is opening",
      detail: "The Order ID and exact amount are now locked by the provider.",
    },
    awaiting_webhook: {
      title: "Checkout reported a failure",
      detail: "Waiting for the signed Razorpay webhook before treating it as verified evidence.",
    },
    browser_success: {
      title: "Browser reported payment success",
      detail: "This is not counted as recovered revenue until server-side evidence confirms it.",
    },
    dismissed: {
      title: "Checkout closed",
      detail: "The provider Order remains auditable. Start a new run when ready.",
    },
    error: {
      title: "The run could not start",
      detail: "No result was invented. Check the safe error below and retry.",
    },
  };

  return copy[state];
}

function liveStateCopy(liveRun: PaymentLabLiveRun): {
  title: string;
  detail: string;
} {
  if (liveRun.current_stage === "completed") {
    if (!liveRun.outcome && liveRun.agent?.recovery_case_status === "escalated") {
      return {
        title: "Safe escalation recorded",
        detail:
          "Deterministic policy stopped automated action and routed the case to human review.",
      };
    }
    if (liveRun.outcome?.status === "recovered") {
      return {
        title: "Revenue recovery verified",
        detail: `${formatMoney(liveRun.outcome.gross_recovered_minor)} is backed by provider and ledger evidence.`,
      };
    }
    if (liveRun.outcome?.status === "duplicate_collection_prevented") {
      return {
        title: "Duplicate collection prevented",
        detail: `${formatMoney(liveRun.outcome.duplicate_collection_prevented_minor)} was protected by the stopping rules.`,
      };
    }
    return {
      title: "Financial outcome verified",
      detail: liveRun.outcome
        ? `The outcome ledger recorded ${humanize(liveRun.outcome.status)}.`
        : "The provider-backed run reached a terminal state.",
    };
  }

  const copy: Record<PaymentLabLiveRun["current_stage"], {
    title: string;
    detail: string;
  }> = {
    checkout: {
      title: "Provider order created",
      detail: "Checkout is live. Waiting for signed provider evidence.",
    },
    failure: {
      title: "Signed payment failure verified",
      detail: "The server correlated the webhook. Recovery may now begin.",
    },
    agent: {
      title:
        liveRun.agent?.agent_run_status === "succeeded"
          ? "Bounded recovery plan persisted"
          : "Bounded recovery agent is running",
      detail: "Gemini proposes; deterministic policy retains authority.",
    },
    outcome: {
      title: liveRun.actions.some((action) => action.provider_action_url)
        ? "Recovery link created"
        : "Creating the provider recovery action",
      detail: "The action is provider-backed. Reconciliation is still required before revenue is counted.",
    },
    completed: {
      title: "Financial outcome verified",
      detail: "The provider-backed run reached a terminal state.",
    },
    failed: {
      title: "Provider run ended safely",
      detail: `No recovery result was invented. Status: ${humanize(liveRun.persisted_status)}.`,
    },
  };

  return copy[liveRun.current_stage];
}

export function PaymentLabLauncher() {
  const failureObservedRef = useRef(false);
  const [checkoutLoaded, setCheckoutLoaded] = useState(false);
  const [mode, setMode] = useState<PaymentLabMode>("guided");
  const [reviewerCode, setReviewerCode] = useState("");
  const [amountRupees, setAmountRupees] = useState("3499");
  const [paymentMethod, setPaymentMethod] =
    useState<PaymentMethod>("netbanking");
  const [runState, setRunState] = useState<RunState>("idle");
  const [run, setRun] = useState<PaymentLabResponse | null>(null);
  const [pollReviewerCode, setPollReviewerCode] = useState("");
  const [safeError, setSafeError] = useState<string | null>(null);
  const [webhookDelayWarning, setWebhookDelayWarning] = useState<string | null>(null);
  const [copiedActionId, setCopiedActionId] = useState<string | null>(null);
  const { liveRun, visibleSteps, polling, pollError } = usePaymentLabLiveRun({
    paymentLabRunId: run?.payment_lab_run_id ?? null,
    reviewerCode: pollReviewerCode,
  });

  const selectedAmountMinor =
    mode === "guided" ? 349_900 : Math.round(Number(amountRupees) * 100);
  const browserFailureAwaitingServer =
    runState === "awaiting_webhook" && liveRun?.current_stage === "checkout";
  const copy =
    liveRun && !browserFailureAwaitingServer
      ? liveStateCopy(liveRun)
      : stateCopy(runState);
  const busy = runState === "creating_order" || runState === "opening_checkout";
  const latestAction = liveRun?.actions.length
    ? liveRun.actions[liveRun.actions.length - 1]
    : null;
  const paymentLinkAction = [...(liveRun?.actions ?? [])].reverse().find(
    (action) =>
      action.action_type === "create_payment_link" &&
      action.provider_action_url !== null,
  );
  const paymentLinkIsActionable = Boolean(
    paymentLinkAction &&
      (!liveRun?.outcome || liveRun.outcome.status === "payment_link_pending") &&
      !["paid", "expired", "cancelled"].includes(
        paymentLinkAction.provider_action_status ?? "",
      ),
  );
  const stepsByKey = new Map(visibleSteps.map((step) => [step.key, step]));
  const paymentAttemptStep = stepsByKey.get("payment_attempt");
  const verifiedFailureStep = stepsByKey.get("verified_failure");
  const recoveryEvidence = [
    stepsByKey.get("recovery_case"),
    stepsByKey.get("agent_recommendation"),
    stepsByKey.get("policy_decision"),
    stepsByKey.get("provider_action"),
  ].filter((step): step is NonNullable<typeof step> => step !== undefined);
  const providerActionStep = stepsByKey.get("provider_action");
  const measuredOutcomeStep = stepsByKey.get("measured_outcome");
  const recoveryStatus: LiveStepStatus = recoveryEvidence.some(
    (step) => step.status === "failed",
  )
    ? "failed"
    : providerActionStep?.status === "completed"
      ? "completed"
      : verifiedFailureStep?.status === "completed"
        ? "active"
        : "pending";
  const outcomeDetail = liveRun?.outcome
    ? liveRun.outcome.status === "payment_link_pending"
      ? "Recovery link created. Waiting for Razorpay to confirm a payment."
      : liveRun.outcome.status === "recovered"
      ? `${formatMoney(liveRun.outcome.gross_recovered_minor)} recovered with provider evidence.`
      : liveRun.outcome.status === "duplicate_collection_prevented"
        ? `${formatMoney(liveRun.outcome.duplicate_collection_prevented_minor)} protected after late authorization.`
        : `Provider outcome: ${humanize(liveRun.outcome.status)}.`
    : providerActionStep?.status === "completed"
      ? "Recovery link created. Waiting for Razorpay to confirm a payment."
      : "No financial result has been recorded yet.";
  const mainPhases: Array<{
    key: string;
    label: string;
    detail: string;
    status: LiveStepStatus;
    occurredAt: string | null;
    icon: LucideIcon;
  }> = [
    {
      key: "attempt",
      label: "Payment attempt",
      detail: paymentAttemptStep?.detail ?? "Creating the Razorpay Test Mode order.",
      status: paymentAttemptStep?.status ?? "active",
      occurredAt: paymentAttemptStep?.occurred_at ?? null,
      icon: CreditCard,
    },
    {
      key: "failure",
      label: "Signed failure verified",
      detail: verifiedFailureStep?.detail ?? "Waiting for signed Razorpay evidence.",
      status: verifiedFailureStep?.status ?? "pending",
      occurredAt: verifiedFailureStep?.occurred_at ?? null,
      icon: ShieldCheck,
    },
    {
      key: "decision",
      label: "Recovery decision",
      detail:
        recoveryStatus === "completed"
          ? "Agent proposal, deterministic policy, and provider action are persisted."
          : recoveryStatus === "active"
            ? "The bounded recovery workflow is evaluating this failure."
            : "Starts only after the signed failure is verified.",
      status: recoveryStatus,
      occurredAt: providerActionStep?.occurred_at ?? null,
      icon: BrainCircuit,
    },
    {
      key: "outcome",
      label: "Provider-verified outcome",
      detail: outcomeDetail,
      status: measuredOutcomeStep?.status ?? "pending",
      occurredAt: liveRun?.outcome?.occurred_at ?? null,
      icon: Banknote,
    },
  ];

  useEffect(() => {
    if (runState !== "awaiting_webhook" || liveRun?.payment) {
      return;
    }

    const timer = window.setTimeout(() => {
      setWebhookDelayWarning(
        "Razorpay Checkout reported a failure, but the signed webhook has not been verified. Check the webhook tunnel and payment consumer logs.",
      );
    }, 15_000);

    return () => window.clearTimeout(timer);
  }, [runState, liveRun?.payment]);

  async function copyRecoveryLink(): Promise<void> {
    if (!paymentLinkAction?.provider_action_url) {
      return;
    }

    try {
      await navigator.clipboard.writeText(paymentLinkAction.provider_action_url);
      setCopiedActionId(paymentLinkAction.recovery_action_id);
    } catch {
      setSafeError("The recovery link could not be copied. Open it directly instead.");
    }
  }

  async function startRun() {
    failureObservedRef.current = false;
    setSafeError(null);
    setWebhookDelayWarning(null);
    setCopiedActionId(null);
    setRun(null);
    setPollReviewerCode("");

    if (!reviewerCode.trim()) {
      setRunState("error");
      setSafeError("Enter the reviewer access code supplied with the demo.");
      return;
    }

    const RazorpayCheckout = window.Razorpay;

    if (!checkoutLoaded || typeof RazorpayCheckout !== "function") {
      setRunState("error");
      setSafeError("Razorpay Checkout is still loading. Retry in a moment.");
      return;
    }

    if (
      mode === "custom" &&
      (!Number.isFinite(selectedAmountMinor) || selectedAmountMinor < 100)
    ) {
      setRunState("error");
      setSafeError("Enter an amount of at least ₹1.");
      return;
    }

    setRunState("creating_order");

    const requestBody =
      mode === "guided"
        ? {
            client_request_id: crypto.randomUUID(),
            mode,
          }
        : {
            client_request_id: crypto.randomUUID(),
            mode,
            amount_minor: selectedAmountMinor,
            payment_method: paymentMethod,
          };

    try {
      const response = await fetch("/api/payment-lab/runs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-ReclaimRail-Reviewer-Code": reviewerCode.trim(),
        },
        body: JSON.stringify(requestBody),
      });

      const responseBody = (await response.json()) as
        | PaymentLabResponse
        | { detail?: string };

      if (!response.ok || !("checkout" in responseBody)) {
        throw new Error(
          "detail" in responseBody && responseBody.detail
            ? responseBody.detail
            : "Payment Lab run creation failed",
        );
      }

      setRun(responseBody);
      setPollReviewerCode(reviewerCode.trim());
      setRunState("opening_checkout");

      const checkout = new RazorpayCheckout({
        key: responseBody.checkout.key_id,
        amount: responseBody.checkout.amount_minor,
        currency: responseBody.checkout.currency,
        name: responseBody.checkout.name,
        description: responseBody.checkout.description,
        order_id: responseBody.checkout.order_id,
        timeout: responseBody.checkout.timeout_seconds,
        theme: { color: responseBody.checkout.theme_color },
        retry: { enabled: false },
        modal: {
          confirm_close: true,
          ondismiss: () =>
            setRunState(
              failureObservedRef.current ? "awaiting_webhook" : "dismissed",
            ),
        },
        handler: () => setRunState("browser_success"),
      });

      checkout.on("payment.failed", () => {
        failureObservedRef.current = true;
        setRunState("awaiting_webhook");
      });
      checkout.open();
    } catch (error) {
      setRunState("error");
      setSafeError(
        error instanceof Error ? error.message : "Payment Lab run creation failed",
      );
    }
  }

  return (
    <>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="afterInteractive"
        onLoad={() => setCheckoutLoaded(true)}
        onError={() => {
          setRunState("error");
          setSafeError("Razorpay Checkout could not be loaded.");
        }}
      />

      <section className={`lab-launcher${run ? " lab-launcher--running" : " lab-launcher--entry"}`} aria-label="Razorpay Test Mode Payment Lab">
        {!run ? <div className="lab-config">
          <div className="lab-start-cue lab-start-cue--hero">
            <span><Play size={20} fill="currentColor" /></span>
            <div>
              <p>One controlled attempt</p>
              <strong>Watch a payment failure become a recovery decision.</strong>
              <p>ReclaimRail reveals each evidence-backed stage only as it arrives.</p>
            </div>
          </div>
          <div className="lab-mode-switch" aria-label="Payment Lab mode">
            <button
              className={mode === "guided" ? "is-active" : ""}
              type="button"
              onClick={() => setMode("guided")}
            >
              Guided live run
              <span>Recommended</span>
            </button>
            <button
              className={mode === "custom" ? "is-active" : ""}
              type="button"
              onClick={() => setMode("custom")}
            >
              Custom run
              <span>Choose inputs</span>
            </button>
          </div>

          <div className="lab-selection">
            <div>
              <span className="lab-field-label">Amount</span>
              {mode === "guided" ? (
                <strong>{formatMoney(349_900)}</strong>
              ) : (
                <label className="lab-input lab-input--amount">
                  <span>₹</span>
                  <input
                    inputMode="decimal"
                    min="1"
                    max="50000"
                    type="number"
                    value={amountRupees}
                    onChange={(event) => setAmountRupees(event.target.value)}
                  />
                </label>
              )}
            </div>
            <div>
              <label className="lab-field-label" htmlFor="payment-method">
                Payment rail
              </label>
              {mode === "guided" ? (
                <strong>Choose in Razorpay Checkout</strong>
              ) : (
                <select
                  id="payment-method"
                  className="lab-input"
                  value={paymentMethod}
                  onChange={(event) =>
                    setPaymentMethod(event.target.value as PaymentMethod)
                  }
                >
                  <option value="upi">UPI</option>
                  <option value="card">Card</option>
                  <option value="netbanking">Netbanking</option>
                  <option value="wallet">Wallet</option>
                </select>
              )}
            </div>
          </div>

          <div className="lab-access">
            <label htmlFor="reviewer-code">Reviewer access code</label>
            <input
              id="reviewer-code"
              autoComplete="off"
              placeholder="Provided with the demo"
              type="password"
              value={reviewerCode}
              onChange={(event) => setReviewerCode(event.target.value)}
            />
            <span>The code is sent only to ReclaimRail&apos;s server proxy.</span>
          </div>

          <button
            className="lab-primary-action"
            disabled={busy}
            type="button"
            onClick={startRun}
          >
            {busy ? <><LoaderCircle className="spin" size={18} /> Preparing secure checkout…</> : <><Play size={18} fill="currentColor" /> Start provider-live recovery <ArrowRight size={18} /></>}
          </button>
          <p className="lab-action-note">
            Razorpay Test Mode · no real money moves · no payment credentials are
            stored by ReclaimRail
          </p>
        </div> : null}

        {run ? <aside
          className={`lab-run-state lab-run-state--${runState}${polling ? " lab-run-state--polling" : ""}`}
          aria-live="polite"
        >
          <div className="lab-run-state__heading">
            <span className="lab-live-dot" aria-hidden="true" />
            <p>Live recovery evidence</p>
            {run ? (
              <span className="lab-poll-state">
                {polling ? "Live" : liveRun?.terminal ? "Verified" : "Paused"}
              </span>
            ) : null}
          </div>
          <div className="lab-run-hero">
            <div>
              {run ? <strong className="lab-run-amount">{formatMoney(run.checkout.amount_minor)}</strong> : null}
              <h2>{copy.title}</h2>
              <p>{copy.detail}</p>
            </div>
            {liveRun ? <span className="lab-run-timer"><Clock3 size={15} /><LiveElapsed startedAt={liveRun.created_at} endedAt={liveRun.terminal ? liveRun.updated_at : null} /></span> : null}
          </div>

          {safeError ? <div className="lab-safe-error">{safeError}</div> : null}
          {pollError ? <div className="lab-poll-warning">{pollError}</div> : null}
          {webhookDelayWarning && runState === "awaiting_webhook" && !liveRun?.payment ? <div className="lab-poll-warning">{webhookDelayWarning}</div> : null}

          {liveRun ? (
            <ol className="lab-story" aria-label="Live recovery progress">
              {mainPhases.map((phase, index) => {
                const PhaseIcon = phase.icon;
                const expanded = phase.key === "decision" && recoveryStatus !== "pending";
                return (
                  <li
                    className={`lab-story__phase lab-story__phase--${phase.status}`}
                    key={phase.key}
                  >
                    <span className="lab-story__rail" aria-hidden="true" />
                    <span className="lab-story__marker">
                      {phase.status === "completed" ? (
                        <Check size={19} strokeWidth={3} />
                      ) : phase.status === "active" ? (
                        <LoaderCircle className="spin" size={19} />
                      ) : (
                        <PhaseIcon size={19} />
                      )}
                    </span>
                    <div className="lab-story__body">
                      <div className="lab-story__topline">
                        <span>Phase {index + 1}</span>
                        <strong>{stepStatusLabel(phase.status)}</strong>
                      </div>
                      <h3>{phase.label}</h3>
                      <p>{phase.detail}</p>
                      {phase.occurredAt ? (
                        <time dateTime={phase.occurredAt}>
                          Recorded {formatTimestamp(phase.occurredAt)} IST
                        </time>
                      ) : null}

                      {expanded ? (
                        <ol className="lab-story__evidence" aria-label="Recovery decision evidence">
                          {recoveryEvidence.map((step) => (
                            <li className={`lab-story__evidence-row lab-story__evidence-row--${step.status}`} key={step.key}>
                              <span>{step.status === "completed" ? <Check size={14} strokeWidth={3} /> : <CircleDot size={14} />}</span>
                              <div><strong>{step.label}</strong><p>{step.detail}</p></div>
                              <em>{stepStatusLabel(step.status)}</em>
                            </li>
                          ))}
                        </ol>
                      ) : null}

                      {phase.key === "decision" && liveRun.agent ? (
                        <div className="lab-story__decision-proof">
                          <div><span>Planner</span><strong>{liveRun.agent.planner_provider ?? "deterministic fallback"}{liveRun.agent.model_name ? ` · ${liveRun.agent.model_name}` : ""}</strong></div>
                          <div><span>Policy</span><strong>{latestAction ? humanize(latestAction.policy_outcome) : "Awaiting policy"}</strong></div>
                          {liveRun.agent.reasoning_summary ? <p>{liveRun.agent.reasoning_summary}</p> : null}
                        </div>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : null}

          {run ? (
            <dl className="lab-run-proof">
              <div>
                <dt>Provider order</dt>
                <dd>{run.checkout.order_id}</dd>
              </div>
              <div>
                <dt>Control state</dt>
                <dd>
                  {liveRun?.terminal && liveRun.agent
                    ? humanize(liveRun.agent.recovery_case_status)
                    : liveRun
                      ? humanize(liveRun.persisted_status)
                      : "checkout ready"}
                </dd>
              </div>
              <div>
                <dt>Verified rail</dt>
                <dd>
                  {formatMoney(run.checkout.amount_minor)} ·{" "}
                  {liveRun?.payment_method ?? "awaiting provider"}
                </dd>
              </div>
              <div>
                <dt>Run ID</dt>
                <dd>{run.payment_lab_run_id.slice(0, 12)}…</dd>
              </div>
            </dl>
          ) : null}

          {paymentLinkAction ? (
            <section className="lab-recovery-link" aria-label="Recovery link">
              <div className="lab-recovery-link__heading">
                <div>
                  <span><Link2 size={15} /> Provider recovery action</span>
                  <strong>
                    {paymentLinkIsActionable
                      ? "Recovery link ready"
                      : liveRun?.outcome?.status === "recovered"
                        ? "Recovery link paid"
                        : `Recovery link ${humanize(paymentLinkAction.provider_action_status ?? "recorded")}`}
                  </strong>
                </div>
                <span className="lab-recovery-link__status">
                  {humanize(paymentLinkAction.provider_action_status ?? "created")}
                </span>
              </div>
              <strong className="lab-recovery-link__amount">{formatMoney(liveRun?.amount_minor ?? run?.checkout.amount_minor ?? 0)}</strong>
              <dl>
                <div>
                  <dt>Link ID</dt>
                  <dd>{paymentLinkAction.provider_action_id ?? "Pending"}</dd>
                </div>
                <div>
                  <dt>Expires</dt>
                  <dd>
                    {paymentLinkAction.provider_action_expires_at
                      ? `${formatTimestamp(paymentLinkAction.provider_action_expires_at)} IST`
                      : "Provider managed"}
                  </dd>
                </div>
              </dl>
              {paymentLinkIsActionable ? (
                <div className="lab-recovery-link__actions">
                  <a
                    href={paymentLinkAction.provider_action_url ?? undefined}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    Open hosted Razorpay Test Link <ExternalLink size={16} />
                  </a>
                  <button type="button" onClick={() => void copyRecoveryLink()}>
                    <Copy size={16} />
                    {copiedActionId === paymentLinkAction.recovery_action_id
                      ? "Copied"
                      : "Copy link"}
                  </button>
                </div>
              ) : null}
              <p>
                ReclaimRail counts recovery only after server-side Razorpay
                reconciliation—not when this link is opened.
              </p>
            </section>
          ) : null}

          <div className="lab-truth-rule">
            <strong><ShieldCheck size={17} /> Evidence rule</strong>
            <span>
              Browser callbacks never update recovered revenue. Signed webhooks and
              provider reconciliation do.
            </span>
          </div>
          <div className="lab-run-links">
            {liveRun?.agent ? (
              <Link
                className="lab-secondary-link"
                href={`/cases/${liveRun.agent.recovery_case_id}`}
              >
                <ClipboardCheck size={16} /> Inspect recovery case
              </Link>
            ) : null}
            <Link className="lab-secondary-link" href={liveRun?.agent ? `/?liveCase=${liveRun.agent.recovery_case_id}#recovery-queue` : "/"}>
              Open command center <ArrowRight size={16} />
            </Link>
            {liveRun?.terminal ? <button className="lab-reset-link" type="button" onClick={() => { setRun(null); setRunState("idle"); setPollReviewerCode(""); }}><RotateCcw size={16} /> Start another run</button> : null}
          </div>
        </aside> : null}
      </section>
    </>
  );
}
