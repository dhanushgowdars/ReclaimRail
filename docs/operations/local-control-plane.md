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
