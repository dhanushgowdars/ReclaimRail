"use client";

import Link from "next/link";
import Script from "next/script";
import { useState } from "react";

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

function formatMoney(amountMinor: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amountMinor / 100);
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
      title: "Payment failure observed",
      detail: "Waiting for the signed Razorpay webhook before the recovery agent may act.",
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

export function PaymentLabLauncher() {
  const [checkoutLoaded, setCheckoutLoaded] = useState(false);
  const [mode, setMode] = useState<PaymentLabMode>("guided");
  const [reviewerCode, setReviewerCode] = useState("");
  const [amountRupees, setAmountRupees] = useState("3499");
  const [paymentMethod, setPaymentMethod] =
    useState<PaymentMethod>("netbanking");
  const [runState, setRunState] = useState<RunState>("idle");
  const [run, setRun] = useState<PaymentLabResponse | null>(null);
  const [safeError, setSafeError] = useState<string | null>(null);

  const selectedAmountMinor =
    mode === "guided" ? 349_900 : Math.round(Number(amountRupees) * 100);
  const copy = stateCopy(runState);
  const busy = runState === "creating_order" || runState === "opening_checkout";

  async function startRun() {
    setSafeError(null);

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
        modal: {
          confirm_close: true,
          ondismiss: () => setRunState("dismissed"),
        },
        handler: () => setRunState("browser_success"),
      });

      checkout.on("payment.failed", () => setRunState("awaiting_webhook"));
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

      <section className="lab-launcher" aria-label="Razorpay Test Mode Payment Lab">
        <div className="lab-config">
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
                <strong>Netbanking</strong>
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
            {busy ? "Preparing secure checkout…" : "Start provider-live recovery"}
          </button>
          <p className="lab-action-note">
            Razorpay Test Mode · no real money moves · no payment credentials are
            stored by ReclaimRail
          </p>
        </div>

        <aside className={`lab-run-state lab-run-state--${runState}`}>
          <div className="lab-run-state__heading">
            <span className="lab-live-dot" />
            <p>Live run evidence</p>
          </div>
          <h2>{copy.title}</h2>
          <p>{copy.detail}</p>

          {safeError ? <div className="lab-safe-error">{safeError}</div> : null}

          {run ? (
            <dl className="lab-run-proof">
              <div>
                <dt>Provider order</dt>
                <dd>{run.checkout.order_id}</dd>
              </div>
              <div>
                <dt>Provenance</dt>
                <dd>Razorpay Test Mode</dd>
              </div>
              <div>
                <dt>Bounded input</dt>
                <dd>
                  {formatMoney(run.checkout.amount_minor)} ·{" "}
                  {run.checkout.payment_method_hint}
                </dd>
              </div>
              <div>
                <dt>Run ID</dt>
                <dd>{run.payment_lab_run_id.slice(0, 12)}…</dd>
              </div>
            </dl>
          ) : null}

          <div className="lab-truth-rule">
            <strong>Evidence rule</strong>
            <span>
              Browser callbacks never update recovered revenue. Signed webhooks and
              provider reconciliation do.
            </span>
          </div>
          <Link className="lab-secondary-link" href="/">
            Open command center
          </Link>
        </aside>
      </section>
    </>
  );
}
