# Local ReclaimRail control plane

Phase 11B replaces session-scoped PowerShell background jobs with one tracked local
process controller. The process manifest contains the API, isolated webhook ingress,
frontend and all eight recovery workers.

## Start

Run from the repository root in Windows PowerShell:

```powershell
.\scripts\ReclaimRail-Local.ps1
```

The controller performs these checks before opening the demo:

1. verifies `uv`, `npm.cmd`, `apps/api/.env` and `apps/web/.env.local`;
2. starts PostgreSQL and Redis unless `-SkipDocker` is supplied;
3. refuses to take ports 3000, 8000 or 8001 from an unknown process;
4. applies pending Alembic migrations;
5. starts the API, webhook ingress, eight workers and frontend;
6. waits for database, Redis, all worker heartbeats and the frontend.

Runtime logs and PID state are written under `.runtime`, which is ignored by Git.

## Inspect

```powershell
.\scripts\ReclaimRail-Local.ps1 -Action Status
Invoke-RestMethod http://127.0.0.1:8000/health/workers
Invoke-RestMethod http://127.0.0.1:8000/health/queues
```

Worker health distinguishes `healthy`, `starting`, `delayed`, `degraded`, `stopping`
and `down`. Queue diagnostics expose database work queues, Redis stream depth, consumer
pending messages and dead letters without returning secrets or raw exception messages.

## Restart or stop

```powershell
.\scripts\ReclaimRail-Local.ps1 -Restart
.\scripts\ReclaimRail-Local.ps1 -Action Stop
```

Shutdown reads only PIDs written by the controller and terminates each explicit process
tree. It never selects arbitrary Python or Node processes and never pipes raw process IDs
into `Stop-Process`.

Cloudflare tunnel startup remains separate because the public URL changes and must be
copied into the Razorpay webhook configuration. ReclaimRail still treats only the signed
webhook ingress as payment truth.

## Human approval gate

Recovery payment-link actions at or above
`RECLAIMRAIL_RECOVERY_APPROVAL_THRESHOLD_MINOR` pause before provider execution. Set a
separate operator credential in `apps/api/.env`:

```dotenv
RECLAIMRAIL_RECOVERY_APPROVAL_THRESHOLD_MINOR=1000000
RECLAIMRAIL_RECOVERY_APPROVAL_TTL_SECONDS=900
RECLAIMRAIL_RECOVERY_OPERATOR_ACCESS_TOKEN=<long-random-operator-secret>
```

The operator queue is intentionally separate from the public demo surface. Every
decision requires the dedicated header, reviewer identity, reason and current approval
version:

```powershell
$Headers = @{ "X-ReclaimRail-Operator-Token" = $env:RR_OPERATOR_TOKEN }
$Queue = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/recovery/approvals?status=pending" `
    -Headers $Headers

$Approval = $Queue.approvals | Select-Object -First 1
$Body = @{
    decision = "approve"
    reviewer_id = "demo-operator"
    reason = "Verified amount, provider failure, and policy evidence"
    expected_version = $Approval.version
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/recovery/approvals/$($Approval.approval_id)/decision" `
    -Headers $Headers `
    -ContentType "application/json" `
    -Body $Body
```

Approval releases only the gated action. The action worker still reloads provider state,
incident context and deterministic policy before any money-facing call. Rejection or
expiry cancels the action and escalates the case; it never silently falls through to
execution.
