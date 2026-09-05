"use client";

import { ArrowRight, LoaderCircle, Play } from "lucide-react";
import Script from "next/script";
import { useEffect, useRef, useState } from "react";

import { LiveRecoveryCommand } from "@/components/live-recovery-command";
import {
  type PaymentLabLiveRun,
  usePaymentLabLiveRun,
} from "@/hooks/use-payment-lab-live-run";
import { formatMoney } from "@/lib/presentation";

type PaymentLabMode = "guided" | "custom";
type DemoTrack = "auto" | "review" | "custom";
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
    prefill_email: string | null;
  };
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
  prefill?: { email: string };
  modal: { ondismiss: () => void; confirm_close: boolean };
  handler: () => void;
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

const AUTO_AMOUNT_MINOR = 349_900;
const DEFAULT_HIGH_VALUE_RUPEES = "10001";
const ACTIVE_RUN_STORAGE_KEY = "reclaimrail.paymentLab.activeRun.v1";

type PersistedActiveRun = {
  run: PaymentLabResponse;
  reviewerCode: string;
  runState: RunState;
  isVerifiedReplay: boolean;
};

function setRunUrl(paymentLabRunId: string | null): void {
  const url = new URL(window.location.href);
  if (paymentLabRunId === null) {
    url.searchParams.delete("payment_lab_run_id");
  } else {
    url.searchParams.set("payment_lab_run_id", paymentLabRunId);
  }
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function persistActiveRun(value: PersistedActiveRun): void {
  window.sessionStorage.setItem(ACTIVE_RUN_STORAGE_KEY, JSON.stringify(value));
  setRunUrl(value.run.payment_lab_run_id);
}

function stateCopy(state: RunState): { title: string; detail: string } {
  const copy: Record<RunState, { title: string; detail: string }> = {
    idle: { title: "Ready for a provider-live run", detail: "Checkout has not been opened yet." },
    creating_order: { title: "Creating a bounded Test Mode order", detail: "The exact amount is being created through ReclaimRail's server proxy." },
    opening_checkout: { title: "Razorpay Checkout is opening", detail: "Choose a Test Mode path; ReclaimRail will wait for provider evidence." },
    awaiting_webhook: { title: "Waiting for provider payment result", detail: "ReclaimRail will begin recovery only after server-verified Razorpay evidence is recorded." },
    browser_success: { title: "Browser callback received", detail: "A browser callback is never treated as a verified financial outcome." },
    dismissed: { title: "Checkout closed", detail: "No recovery case is created until provider evidence reaches the server." },
    error: { title: "The run could not start", detail: "No payment or recovery result was invented." },
  };
  return copy[state];
}

export function PaymentLabLauncher() {
  const failureObservedRef = useRef(false);
  const [checkoutLoaded, setCheckoutLoaded] = useState(false);
  const [demoTrack, setDemoTrack] = useState<DemoTrack>("auto");
  const [reviewerCode, setReviewerCode] = useState("");
  const [amountRupees, setAmountRupees] = useState("3499");
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("netbanking");
  const [enableTestEmailNotification, setEnableTestEmailNotification] = useState(false);
  const [runState, setRunState] = useState<RunState>("idle");
  const [run, setRun] = useState<PaymentLabResponse | null>(null);
  const [pollReviewerCode, setPollReviewerCode] = useState("");
  const [isVerifiedReplay, setIsVerifiedReplay] = useState(false);
  const [safeError, setSafeError] = useState<string | null>(null);
  const [webhookDelayWarning, setWebhookDelayWarning] = useState<string | null>(null);
  const [copiedActionId, setCopiedActionId] = useState<string | null>(null);
  const [approvingApprovalId, setApprovingApprovalId] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const { liveRun, polling, pollError } = usePaymentLabLiveRun({
    paymentLabRunId: run?.payment_lab_run_id ?? null,
    reviewerCode: pollReviewerCode,
  });
  const selectedAmountMinor = demoTrack === "auto" ? AUTO_AMOUNT_MINOR : Math.round(Number(amountRupees) * 100);
  const busy = runState === "creating_order" || runState === "opening_checkout";
  const copy = stateCopy(runState);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const stored = window.sessionStorage.getItem(ACTIVE_RUN_STORAGE_KEY);
      if (stored === null) return;
      try {
        const restored = JSON.parse(stored) as Partial<PersistedActiveRun>;
        if (
          restored.run?.payment_lab_run_id &&
          restored.run.checkout &&
          typeof restored.reviewerCode === "string" &&
          restored.reviewerCode.length > 0
        ) {
          setRun(restored.run);
          setReviewerCode(restored.reviewerCode);
          setPollReviewerCode(restored.reviewerCode);
          setRunState(restored.runState ?? "awaiting_webhook");
          setIsVerifiedReplay(Boolean(restored.isVerifiedReplay));
          setRunUrl(restored.run.payment_lab_run_id);
        }
      } catch {
        window.sessionStorage.removeItem(ACTIVE_RUN_STORAGE_KEY);
        setRunUrl(null);
      }
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (isVerifiedReplay || runState !== "awaiting_webhook" || liveRun?.payment) return;
    const timer = window.setTimeout(() => {
      setWebhookDelayWarning("Razorpay evidence is taking longer than usual. ReclaimRail is verifying the provider result from the server.");
    }, 30_000);
    return () => window.clearTimeout(timer);
  }, [isVerifiedReplay, liveRun?.payment, runState]);

  function resetRun(): void {
    failureObservedRef.current = false;
    setRun(null);
    setRunState("idle");
    setPollReviewerCode("");
    setIsVerifiedReplay(false);
    setSafeError(null);
    setWebhookDelayWarning(null);
    setCopiedActionId(null);
    setApprovingApprovalId(null);
    setApprovalError(null);
    window.sessionStorage.removeItem(ACTIVE_RUN_STORAGE_KEY);
    setRunUrl(null);
  }

  async function copyRecoveryLink(): Promise<void> {
    const action = [...(liveRun?.actions ?? [])].reverse().find((candidate) => candidate.action_type === "create_payment_link" && candidate.provider_action_url !== null);
    if (!action?.provider_action_url) return;
    try {
      await navigator.clipboard.writeText(action.provider_action_url);
      setCopiedActionId(action.recovery_action_id);
    } catch {
      setSafeError("The recovery link could not be copied. Open it directly instead.");
    }
  }

  async function decideApproval(
    decision: "approve" | "reject",
    optionalReason: string,
  ): Promise<void> {
    const approval = liveRun?.approval;
    if (!approval || approval.status !== "pending" || !pollReviewerCode) return;

    setApprovingApprovalId(approval.approval_id);
    setApprovalError(null);
    const reason = optionalReason.trim() || (
      decision === "approve"
        ? "Approved during protected demo review"
        : "Declined during protected demo review"
    );

    try {
      const response = await fetch(
        `/api/recovery/approvals/${encodeURIComponent(approval.approval_id)}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-ReclaimRail-Reviewer-Code": pollReviewerCode,
          },
          body: JSON.stringify({
            decision,
            reviewer_id: "payment-lab-demo-operator",
            reason,
            expected_version: approval.version,
          }),
        },
      );
      const responseBody = (await response.json()) as { detail?: string };
      if (!response.ok) {
        throw new Error(responseBody.detail ?? "The protected review decision was not recorded");
      }
    } catch (error) {
      setApprovalError(
        error instanceof Error
          ? error.message
          : "The protected review decision was not recorded",
      );
    } finally {
      setApprovingApprovalId(null);
    }
  }

  async function startRun(): Promise<void> {
    failureObservedRef.current = false;
    setSafeError(null);
    setWebhookDelayWarning(null);
    setCopiedActionId(null);
    setApprovalError(null);
    setApprovingApprovalId(null);
    setRun(null);
    setPollReviewerCode("");
    setIsVerifiedReplay(false);
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
    if (!Number.isFinite(selectedAmountMinor) || selectedAmountMinor < 100) {
      setRunState("error");
      setSafeError("Enter an amount of at least ₹1.");
      return;
    }
    setRunState("creating_order");
    const mode: PaymentLabMode = demoTrack === "auto" ? "guided" : "custom";
    const requestBody = mode === "guided"
      ? { client_request_id: crypto.randomUUID(), mode, enable_test_email_recovery_notification: enableTestEmailNotification }
      : { client_request_id: crypto.randomUUID(), mode, amount_minor: selectedAmountMinor, payment_method: paymentMethod, enable_test_email_recovery_notification: enableTestEmailNotification };
    try {
      const response = await fetch("/api/payment-lab/runs", { method: "POST", headers: { "Content-Type": "application/json", "X-ReclaimRail-Reviewer-Code": reviewerCode.trim() }, body: JSON.stringify(requestBody) });
      const responseBody = (await response.json()) as PaymentLabResponse | { detail?: string };
      if (!response.ok || !("checkout" in responseBody)) {
        throw new Error("detail" in responseBody && responseBody.detail ? responseBody.detail : "Payment Lab run creation failed");
      }
      setRun(responseBody);
      const normalizedReviewerCode = reviewerCode.trim();
      setPollReviewerCode(normalizedReviewerCode);
      setRunState("opening_checkout");
      persistActiveRun({
        run: responseBody,
        reviewerCode: normalizedReviewerCode,
        runState: "awaiting_webhook",
        isVerifiedReplay: false,
      });
      openCheckout(responseBody);
    } catch (error) {
      setRunState("error");
      setSafeError(error instanceof Error ? error.message : "Payment Lab run creation failed");
    }
  }

  function openCheckout(checkoutRun: PaymentLabResponse | null = run): void {
    const RazorpayCheckout = window.Razorpay;
    if (!checkoutRun || !checkoutLoaded || typeof RazorpayCheckout !== "function") {
      setSafeError("Razorpay Checkout is not ready. Refresh once, then use Open Razorpay Checkout.");
      return;
    }

    setSafeError(null);
    setRunState("opening_checkout");
    const checkout = new RazorpayCheckout({
      key: checkoutRun.checkout.key_id, amount: checkoutRun.checkout.amount_minor, currency: checkoutRun.checkout.currency,
      name: checkoutRun.checkout.name, description: checkoutRun.checkout.description, order_id: checkoutRun.checkout.order_id,
      timeout: checkoutRun.checkout.timeout_seconds, theme: { color: checkoutRun.checkout.theme_color }, retry: { enabled: false },
      ...(checkoutRun.checkout.prefill_email ? { prefill: { email: checkoutRun.checkout.prefill_email } } : {}),
      modal: { confirm_close: true, ondismiss: () => setRunState(failureObservedRef.current ? "awaiting_webhook" : "dismissed") },
      handler: () => setRunState("browser_success"),
    });
    checkout.on("payment.failed", () => {
      failureObservedRef.current = true;
      setRunState("awaiting_webhook");
    });
    checkout.open();
    setRunState("awaiting_webhook");
  }

  async function openVerifiedReplay(): Promise<void> {
    if (!reviewerCode.trim()) {
      setSafeError("Enter the reviewer access code to open a recorded Test Mode replay.");
      return;
    }
    try {
      const response = await fetch("/api/payment-lab/runs?verified_replay=latest", { cache: "no-store", headers: { "X-ReclaimRail-Reviewer-Code": reviewerCode.trim() } });
      const responseBody = (await response.json()) as PaymentLabLiveRun | { detail?: string };
      if (!response.ok || !("steps" in responseBody)) {
        throw new Error("detail" in responseBody && responseBody.detail ? responseBody.detail : "No completed Test Mode replay is available yet");
      }
      setRun({
        payment_lab_run_id: responseBody.payment_lab_run_id, client_request_id: responseBody.client_request_id,
        mode: responseBody.mode === "guided" ? "guided" : "custom", provenance: "razorpay_test", status: "checkout_ready", test_mode: true,
        checkout_expires_at: responseBody.checkout_expires_at,
        checkout: { key_id: "", order_id: responseBody.provider_order_id ?? "Recorded Test Mode run", amount_minor: responseBody.amount_minor, currency: responseBody.currency, name: "Recorded Test Mode replay", description: "Verified provider-backed replay", timeout_seconds: 0, theme_color: "#2563eb", payment_method_hint: responseBody.payment_method as PaymentMethod, prefill_email: null },
      });
      setPollReviewerCode(reviewerCode.trim());
      setIsVerifiedReplay(true);
      setWebhookDelayWarning(null);
      setSafeError(null);
      setRunState("idle");
      persistActiveRun({
        run: {
          payment_lab_run_id: responseBody.payment_lab_run_id, client_request_id: responseBody.client_request_id,
          mode: responseBody.mode === "guided" ? "guided" : "custom", provenance: "razorpay_test", status: "checkout_ready", test_mode: true,
          checkout_expires_at: responseBody.checkout_expires_at,
          checkout: { key_id: "", order_id: responseBody.provider_order_id ?? "Recorded Test Mode run", amount_minor: responseBody.amount_minor, currency: responseBody.currency, name: "Recorded Test Mode replay", description: "Verified provider-backed replay", timeout_seconds: 0, theme_color: "#2563eb", payment_method_hint: responseBody.payment_method as PaymentMethod, prefill_email: null },
        },
        reviewerCode: reviewerCode.trim(),
        runState: "idle",
        isVerifiedReplay: true,
      });
    } catch (error) {
      setSafeError(error instanceof Error ? error.message : "The verified replay could not be opened");
    }
  }

  return <>
    <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="afterInteractive" onLoad={() => setCheckoutLoaded(true)} onError={() => { setRunState("error"); setSafeError("Razorpay Checkout could not be loaded."); }} />
    <section className={`lab-launcher${run ? " lab-launcher--running" : " lab-launcher--entry"}`} aria-label="Razorpay Test Mode Payment Lab">
      {!run ? <div className="lab-config">
        <div className="lab-start-cue lab-start-cue--hero"><span><Play size={20} fill="currentColor" /></span><div><p>Provider-backed live demo</p><strong>Choose the recovery story you want to prove.</strong><p>ReclaimRail advances only when Razorpay evidence is verified and stored by the server.</p></div></div>
        <div className="lab-mode-switch lab-mode-switch--three" aria-label="Choose a demo path">
          <button className={demoTrack === "auto" ? "is-active" : ""} type="button" onClick={() => setDemoTrack("auto")}>Auto-recovery · ₹3,499<span>Netbanking · policy can execute</span></button>
          <button className={demoTrack === "review" ? "is-active" : ""} type="button" onClick={() => { setDemoTrack("review"); setAmountRupees((value) => Number(value) > 10_000 ? value : DEFAULT_HIGH_VALUE_RUPEES); }}>High-value review<span>Choose any amount above the review threshold</span></button>
          <button className={demoTrack === "custom" ? "is-active" : ""} type="button" onClick={() => setDemoTrack("custom")}>Custom amount<span>Choose amount and payment rail</span></button>
        </div>
        <div className="lab-selection"><div><span className="lab-field-label">Recovery amount</span>{demoTrack === "auto" ? <strong>{formatMoney(selectedAmountMinor)}</strong> : <label className="lab-input lab-input--amount"><span>₹</span><input inputMode="decimal" min="1" type="number" value={amountRupees} onChange={(event) => setAmountRupees(event.target.value)} /></label>}{demoTrack === "review" ? <small>Any amount above the configured threshold will enter protected review.</small> : null}</div><div><label className="lab-field-label" htmlFor="payment-method">Payment rail</label>{demoTrack === "auto" ? <strong>Choose in Razorpay Checkout</strong> : <select id="payment-method" className="lab-input" value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value as PaymentMethod)}><option value="netbanking">Netbanking</option><option value="upi">UPI</option><option value="card">Card</option><option value="wallet">Wallet</option></select>}</div></div>
        <label className="lab-notification-consent"><input checked={enableTestEmailNotification} type="checkbox" onChange={(event) => setEnableTestEmailNotification(event.target.checked)} /><span><strong>Send one controlled test-email notification if policy allows</strong><small>Uses only the configured consented, allowlisted demo inbox.</small></span></label>
        <div className="lab-access"><label htmlFor="reviewer-code">Reviewer access code</label><input id="reviewer-code" autoComplete="off" placeholder="Provided with the demo" type="password" value={reviewerCode} onChange={(event) => setReviewerCode(event.target.value)} /><span>The code is sent only to ReclaimRail&apos;s server proxy.</span></div>
        <button className="lab-primary-action" disabled={busy} type="button" onClick={() => void startRun()}>{busy ? <><LoaderCircle className="spin" size={18} /> Preparing secure checkout…</> : <><Play size={18} fill="currentColor" /> Start this provider-live demo <ArrowRight size={18} /></>}</button>
        <p className="lab-action-note">Razorpay Test Mode · no real money moves · no payment credentials are stored by ReclaimRail</p>
      </div> : <LiveRecoveryCommand run={run} liveRun={liveRun} polling={polling} title={copy.title} detail={copy.detail} safeError={safeError} pollError={pollError} webhookDelayWarning={webhookDelayWarning} isVerifiedReplay={isVerifiedReplay} copiedActionId={copiedActionId} onCopyRecoveryLink={() => void copyRecoveryLink()} onOpenVerifiedReplay={() => void openVerifiedReplay()} onOpenCheckout={() => openCheckout()} onStartAnotherRun={resetRun} approvingApprovalId={approvingApprovalId} approvalError={approvalError} onApprovalDecision={(decision, reason) => void decideApproval(decision, reason)} />}
    </section>
  </>;
}
