"use client";

import { useEffect, useState } from "react";

export type PaymentLabLiveStepStatus =
  | "pending"
  | "active"
  | "completed"
  | "failed";

export type PaymentLabLiveRun = {
  payment_lab_run_id: string;
  client_request_id: string;
  mode: string;
  provenance: string;
  persisted_status: string;
  current_stage:
    | "checkout"
    | "failure"
    | "agent"
    | "outcome"
    | "completed"
    | "failed";
  terminal: boolean;
  poll_after_milliseconds: number | null;
  amount_minor: number;
  currency: string;
  payment_method: string;
  provider_order_id: string | null;
  provider_order_status: string | null;
  failure_code: string | null;
  checkout_expires_at: string;
  created_at: string;
  updated_at: string;
  steps: Array<{
    key: string;
    label: string;
    status: PaymentLabLiveStepStatus;
    occurred_at: string | null;
    detail: string;
  }>;
  payment: {
    payment_attempt_id: string;
    provider_payment_id: string;
    current_state: string;
    failure_code: string | null;
    failure_reason: string | null;
    observed_at: string;
  } | null;
  agent: {
    recovery_case_id: string;
    recovery_case_status: string;
    agent_run_id: string | null;
    agent_run_status: string | null;
    planner_provider: string | null;
    model_name: string | null;
    fallback_used: boolean | null;
    fallback_reason: string | null;
    reasoning_summary: string | null;
    proposed_action_count: number;
    completed_at: string | null;
  } | null;
  actions: Array<{
    recovery_action_id: string;
    sequence_number: number;
    action_type: string;
    status: string;
    policy_outcome: string;
    policy_guardrails: string[];
    policy_explanation: string;
    provider_action_id: string | null;
    provider_action_status: string | null;
    provider_action_url: string | null;
    provider_action_expires_at: string | null;
    completed_at: string | null;
  }>;
  outcome: {
    recovery_outcome_id: string;
    status: string;
    attribution: string;
    gross_recovered_minor: number;
    duplicate_collection_prevented_minor: number;
    evidence_event_count: number;
    occurred_at: string;
  } | null;
};

type UsePaymentLabLiveRunOptions = {
  paymentLabRunId: string | null;
  reviewerCode: string;
};

const DEFAULT_POLL_DELAY_MILLISECONDS = 1000;
const RETRY_DELAY_MILLISECONDS = 2500;

function boundedPollDelay(delay: number | null): number {
  if (delay === null || !Number.isFinite(delay)) {
    return DEFAULT_POLL_DELAY_MILLISECONDS;
  }
  return Math.min(Math.max(delay, 500), 5000);
}

export function usePaymentLabLiveRun({
  paymentLabRunId,
  reviewerCode,
}: UsePaymentLabLiveRunOptions): {
  liveRun: PaymentLabLiveRun | null;
  visibleSteps: PaymentLabLiveRun["steps"];
  polling: boolean;
  pollError: string | null;
  catchingUp: boolean;
} {
  const [liveRunSnapshot, setLiveRunSnapshot] = useState<{
    paymentLabRunId: string;
    liveRun: PaymentLabLiveRun;
  } | null>(null);
  const [pollFailure, setPollFailure] = useState<{
    paymentLabRunId: string;
    message: string;
    retrying: boolean;
  } | null>(null);
  const [playback, setPlayback] = useState<{
    paymentLabRunId: string;
    visibleCount: number;
    targetCount: number;
  } | null>(null);

  const liveRun =
    liveRunSnapshot?.paymentLabRunId === paymentLabRunId
      ? liveRunSnapshot.liveRun
      : null;
  const currentPollFailure =
    pollFailure?.paymentLabRunId === paymentLabRunId ? pollFailure : null;
  const pollError = currentPollFailure?.message ?? null;
  const polling = Boolean(
    paymentLabRunId &&
      reviewerCode &&
      !liveRun?.terminal &&
      currentPollFailure?.retrying !== false,
  );
  const currentPlayback =
    playback?.paymentLabRunId === paymentLabRunId ? playback : null;
  const visibleSteps = liveRun?.steps.slice(0, currentPlayback?.visibleCount ?? 0) ?? [];
  const catchingUp = Boolean(
    currentPlayback && currentPlayback.visibleCount < currentPlayback.targetCount,
  );

  useEffect(() => {
    if (!currentPlayback || currentPlayback.visibleCount >= currentPlayback.targetCount) {
      return;
    }
    const timer = window.setTimeout(() => {
      setPlayback((current) =>
        current?.paymentLabRunId === currentPlayback.paymentLabRunId
          ? {
              ...current,
              visibleCount: Math.min(current.visibleCount + 1, current.targetCount),
            }
          : current,
      );
    }, 520);
    return () => window.clearTimeout(timer);
  }, [currentPlayback]);

  useEffect(() => {
    if (!paymentLabRunId || !reviewerCode) {
      return;
    }

    const runId = paymentLabRunId;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeRequest: AbortController | undefined;

    async function poll(): Promise<void> {
      activeRequest = new AbortController();

      try {
        const query = new URLSearchParams({
          payment_lab_run_id: runId,
        });
        const response = await fetch(`/api/payment-lab/runs?${query}`, {
          cache: "no-store",
          signal: activeRequest.signal,
          headers: {
            Accept: "application/json",
            "X-ReclaimRail-Reviewer-Code": reviewerCode,
          },
        });
        const responseBody = (await response.json()) as
          | PaymentLabLiveRun
          | { detail?: string };

        if (cancelled) {
          return;
        }

        if (!response.ok || !("steps" in responseBody)) {
          const retrying = response.status === 429 || response.status >= 500;
          const message =
            "detail" in responseBody && responseBody.detail
              ? responseBody.detail
              : "Live evidence is temporarily unavailable";

          setPollFailure({
            paymentLabRunId: runId,
            message: retrying
              ? `${message}. Retrying automatically.`
              : message,
            retrying,
          });
          if (retrying) {
            timer = setTimeout(() => void poll(), RETRY_DELAY_MILLISECONDS);
          }
          return;
        }

        setLiveRunSnapshot({
          paymentLabRunId: runId,
          liveRun: responseBody,
        });
        const lastReadyStepIndex = responseBody.steps.findLastIndex(
          (step) => step.status !== "pending",
        );
        const visibleStepTarget = Math.max(1, lastReadyStepIndex + 1);
        setPlayback((current) => {
          if (current?.paymentLabRunId !== runId) {
            return {
              paymentLabRunId: runId,
              visibleCount: Math.min(2, visibleStepTarget),
              targetCount: visibleStepTarget,
            };
          }
          return {
            ...current,
            targetCount: Math.max(current.targetCount, visibleStepTarget),
          };
        });
        setPollFailure(null);

        if (responseBody.terminal) {
          return;
        }

        timer = setTimeout(
          () => void poll(),
          boundedPollDelay(responseBody.poll_after_milliseconds),
        );
      } catch (error) {
        if (cancelled || activeRequest?.signal.aborted) {
          return;
        }

        setPollFailure({
          paymentLabRunId: runId,
          message:
            error instanceof Error
              ? `${error.message}. Retrying automatically.`
              : "Live evidence is temporarily unavailable. Retrying automatically.",
          retrying: true,
        });
        timer = setTimeout(() => void poll(), RETRY_DELAY_MILLISECONDS);
      }
    }

    void poll();

    return () => {
      cancelled = true;
      activeRequest?.abort();
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [paymentLabRunId, reviewerCode]);

  return { liveRun, visibleSteps, polling, pollError, catchingUp };
}
