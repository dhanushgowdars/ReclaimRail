export type RecoveryDashboardSummary = {
  currency: string;
  revenue_at_risk_minor: number;
  verified_recovered_minor: number;
  duplicate_collection_prevented_minor: number;
  active_incident_revenue_at_risk_minor: number;
  active_case_count: number;
  recovered_case_count: number;
  pending_outcome_count: number;
  open_incident_count: number;
  generated_at: string;
};

export type RecoveryIncident = {
  incident_id: string;
  status: string;
  severity: string;
  scope: string;
  dimension_value: string;
  currency: string;
  revenue_at_risk_minor: number;
  failure_rate: number;
  baseline_failure_rate: number;
  absolute_uplift: number;
  rate_multiplier: number | null;
  confidence: number;
  occurrence_count: number;
  reason_codes: string[];
  first_detected_at: string;
  last_detected_at: string;
};

export type RecoveryCaseQueueItem = {
  recovery_case_id: string;
  status: string;
  amount_minor: number;
  currency: string;
  payment_method: string | null;
  source_incident_id: string | null;
  recovery_attempt_count: number;
  next_action_at: string | null;
  late_authorization_detected_at: string | null;
  opened_at: string;
  updated_at: string;
  latest_action_type: string | null;
  latest_action_status: string | null;
  latest_action_policy_outcome: string | null;
  outcome_status: string | null;
};

export type RecoveryCaseQueuePage = {
  items: RecoveryCaseQueueItem[];
  total_count: number;
  limit: number;
  offset: number;
};

export type RecoveryOutcome = {
  recovery_outcome_id: string;
  recovery_case_id: string;
  recovery_action_id: string | null;
  status: string;
  attribution: string;
  original_amount_minor: number;
  gross_recovered_minor: number;
  reversed_minor: number;
  duplicate_collection_prevented_minor: number;
  currency: string;
  payment_link_id: string | null;
  evidence_event_count: number;
  occurred_at: string;
  updated_at: string;
};

export type RecoveryOutcomePage = {
  items: RecoveryOutcome[];
  total_count: number;
  limit: number;
  offset: number;
};

export type RecoveryApproval = {
  approval_id: string;
  recovery_case_id: string;
  recovery_action_id: string;
  status: string;
  request_reason: string;
  amount_minor: number;
  currency: string;
  threshold_minor: number | null;
  request_context: Record<string, unknown>;
  requested_at: string;
  expires_at: string;
  version: number;
};

export type RecoveryCaseDetail = {
  recovery_case: {
    recovery_case_id: string;
    status: string;
    amount_minor: number;
    currency: string;
    payment_method: string | null;
    source_incident_id: string | null;
    recovery_attempt_count: number;
    active_payment_link_id: string | null;
    next_action_at: string | null;
    late_authorization_detected_at: string | null;
    opened_at: string;
    recovered_at: string | null;
    closed_at: string | null;
    close_reason: string | null;
  };
  payment_lifecycle: {
    payment_attempt_id: string;
    current_state: string;
    state_version: number;
    amount_minor: number;
    currency: string;
    payment_method: string | null;
    error_code: string | null;
    error_source: string | null;
    error_step: string | null;
    error_reason: string | null;
    recovery_eligible: boolean;
    recovery_stopped_at: string | null;
    recovery_stop_reason: string | null;
    late_authorization_detected_at: string | null;
  };
  agent_runs: Array<{
    agent_run_id: string;
    run_number: number;
    status: string;
    planner_provider: string;
    model_name: string | null;
    prompt_version: string;
    reasoning_summary: string | null;
    proposed_action_count: number;
    failure_code: string | null;
    started_at: string;
    completed_at: string | null;
  }>;
  actions: Array<{
    recovery_action_id: string;
    agent_run_id: string;
    sequence_number: number;
    action_type: string;
    status: string;
    proposal_reason: string;
    amount_minor: number | null;
    currency: string | null;
    channel: string | null;
    target_payment_method: string | null;
    execute_after: string | null;
    policy_outcome: string;
    policy_guardrails: string[];
    policy_explanation: string;
    policy_version: string;
    policy_evaluated_at: string;
    execution_attempt_count: number;
    provider_action_id: string | null;
    provider_action_status: string | null;
    provider_action_url: string | null;
    provider_action_expires_at: string | null;
    started_at: string | null;
    completed_at: string | null;
  }>;
  outcome: {
    recovery_outcome_id: string;
    status: string;
    attribution: string;
    recovery_action_id: string | null;
    payment_link_id: string | null;
    gross_recovered_minor: number;
    reversed_minor: number;
    duplicate_collection_prevented_minor: number;
    evidence_event_count: number;
    occurred_at: string;
    updated_at: string;
  } | null;
  payment_transitions: Array<{
    event_type: string;
    previous_state: string;
    incoming_state: string;
    resulting_state: string;
    resulting_version: number;
    outcome: string;
    reason: string;
    late_authorization: boolean;
    stop_recovery: boolean;
    event_created_at: string;
    processed_at: string;
  }>;
  audit_chain: {
    valid: boolean;
    reason: string;
    checked_event_count: number;
    broken_sequence_number: number | null;
    total_event_count: number;
    timeline_truncated: boolean;
    events: Array<{
      sequence_number: number;
      event_type: string;
      actor_type: string;
      recovery_action_id: string | null;
      previous_event_hash: string | null;
      event_hash: string;
      hash_algorithm: string;
      occurred_at: string;
      provider_status: string | null;
      outcome_status: string | null;
    }>;
  };
};

function getApiBaseUrl(): string {
  return (
    process.env.RECLAIMRAIL_API_BASE_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8000"
  );
}

async function getRecoveryApiJson<T>(path: string): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Recovery API request failed (${response.status})`);
  }

  return (await response.json()) as T;
}

export async function loadRecoveryDashboard(caseLimit = 8): Promise<{
  summary: RecoveryDashboardSummary;
  incidents: RecoveryIncident[];
  cases: RecoveryCaseQueuePage;
  outcomes: RecoveryOutcomePage;
}> {
  const [summary, incidents, cases, outcomes] = await Promise.all([
    getRecoveryApiJson<RecoveryDashboardSummary>("/recovery/dashboard/summary"),
    getRecoveryApiJson<RecoveryIncident[]>("/recovery/dashboard/incidents?limit=5"),
    getRecoveryApiJson<RecoveryCaseQueuePage>(`/recovery/dashboard/cases?limit=${caseLimit}`),
    getRecoveryApiJson<RecoveryOutcomePage>("/recovery/dashboard/outcomes?limit=6"),
  ]);

  return { summary, incidents, cases, outcomes };
}

export async function loadRecoveryApprovals(): Promise<RecoveryApproval[]> {
  const operatorToken = process.env.RECLAIMRAIL_RECOVERY_OPERATOR_ACCESS_TOKEN?.trim();
  if (!operatorToken) return [];
  const response = await fetch(`${getApiBaseUrl()}/recovery/approvals?status=pending&limit=100`, {
    cache: "no-store",
    headers: { Accept: "application/json", "X-ReclaimRail-Operator-Token": operatorToken },
  });
  if (!response.ok) throw new Error(`Recovery approval request failed (${response.status})`);
  const payload = (await response.json()) as { approvals: RecoveryApproval[] };
  return payload.approvals;
}

export async function loadRecoveryCaseDetail(
  recoveryCaseId: string,
): Promise<RecoveryCaseDetail> {
  return getRecoveryApiJson<RecoveryCaseDetail>(
    `/recovery/dashboard/cases/${encodeURIComponent(recoveryCaseId)}`,
  );
}
