[CmdletBinding()]
param(
    [switch]$ConfirmReset
)

$ErrorActionPreference = "Stop"

if (-not $ConfirmReset) {
    throw "This removes recovery cases opened before today in India. Re-run with -ConfirmReset."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Sql = @"
BEGIN;
CREATE TEMP TABLE cleanup_case_ids ON COMMIT DROP AS
SELECT id
FROM recovery_cases
WHERE opened_at < (
    date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
    AT TIME ZONE 'Asia/Kolkata'
);

SELECT count(*) AS older_cases_selected
FROM cleanup_case_ids;

DELETE FROM recovery_outcomes
WHERE recovery_case_id IN (SELECT id FROM cleanup_case_ids);

DELETE FROM recovery_cases
WHERE id IN (SELECT id FROM cleanup_case_ids);

-- Recovery cases are the durable workflow owner.  When an older demo case is
-- removed, retire its orphaned Payment Lab run as well; otherwise the recovery
-- worker will rediscover the run forever and starve newer live runs.
UPDATE payment_lab_runs AS run
SET
    status = 'expired',
    updated_at = now(),
    version = run.version + 1
WHERE run.status IN ('payment_attempted', 'recovery_running')
  AND run.created_at < (
      date_trunc('day', now() AT TIME ZONE 'Asia/Kolkata')
      AT TIME ZONE 'Asia/Kolkata'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM recovery_cases AS recovery_case
      WHERE recovery_case.payment_attempt_id = run.payment_attempt_id
  );
COMMIT;
"@

Push-Location $RepoRoot
try {
    $Sql | docker compose exec -T postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    if ($LASTEXITCODE -ne 0) {
        throw "Database reset failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Host "Recovery cases opened before today (India time) were removed." -ForegroundColor Green
Write-Host "Today's recovery cases and their linked evidence were preserved." -ForegroundColor Green
Write-Host "Dependent old outcomes, approvals, actions, agent runs, and audit records were removed." -ForegroundColor Cyan
Write-Host "Older orphaned Payment Lab runs were marked expired so they cannot block new runs." -ForegroundColor Cyan
Write-Host "Database schema, configuration, and controlled Evidence Lab tests were preserved." -ForegroundColor Cyan
