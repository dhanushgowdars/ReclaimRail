[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Status")]
    [string]$Action = "Start",
    [switch]$Restart,
    [switch]$SkipDocker,
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ManifestPath = Join-Path $RepoRoot "ops\local-processes.json"
$RuntimePath = Join-Path $RepoRoot ".runtime"
$LogPath = Join-Path $RuntimePath "logs"
$StatePath = Join-Path $RuntimePath "local-processes.json"

function Read-ProcessManifest {
    if (-not (Test-Path $ManifestPath)) {
        throw "Local process manifest is missing: $ManifestPath"
    }
    return Get-Content $ManifestPath -Raw | ConvertFrom-Json
}

function Read-RuntimeState {
    if (-not (Test-Path $StatePath)) {
        return @()
    }
    $State = Get-Content $StatePath -Raw | ConvertFrom-Json
    return @($State.processes)
}

function Get-ProcessIdentity {
    param([int]$ProcessId)
    try {
        $Process = Get-Process -Id $ProcessId -ErrorAction Stop
        return [pscustomobject]@{
            name = $Process.ProcessName
            started_at_utc = $Process.StartTime.ToUniversalTime().ToString("o")
        }
    }
    catch {
        return $null
    }
}

function Test-TrackedProcessAlive {
    param($Entry)
    $Identity = Get-ProcessIdentity -ProcessId ([int]$Entry.pid)
    if ($null -eq $Identity) {
        return $false
    }

    # PID values are reusable on Windows. Never treat a process as ReclaimRail
    # unless both its executable identity and start time match the process that
    # this launcher recorded.
    if ($null -eq $Entry.process_name -or $null -eq $Entry.process_started_at_utc) {
        return $false
    }

    return (
        $Identity.name -ieq [string]$Entry.process_name -and
        $Identity.started_at_utc -eq [string]$Entry.process_started_at_utc
    )
}

function Stop-KnownProcesses {
    $Entries = @(Read-RuntimeState)
    foreach ($Entry in ($Entries | Sort-Object started_order -Descending)) {
        $ProcessId = [int]$Entry.pid
        if (-not (Test-TrackedProcessAlive -Entry $Entry)) {
            continue
        }

        Write-Host "Stopping $($Entry.name) (PID $ProcessId)..." -ForegroundColor Yellow
        & taskkill.exe /PID $ProcessId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Test-TrackedProcessAlive -Entry $Entry)) {
            throw "Unable to stop $($Entry.name) (PID $ProcessId)."
        }
    }

    if (Test-Path $StatePath) {
        Remove-Item -LiteralPath $StatePath -Force
    }
}

function Show-ReclaimRailStatus {
    $Entries = @(Read-RuntimeState)
    if ($Entries.Count -eq 0) {
        Write-Host "No ReclaimRail runtime state was found." -ForegroundColor Yellow
    }
    else {
        $Entries |
            Select-Object name, pid, @{Name="running"; Expression={
                Test-TrackedProcessAlive -Entry $_
            }}, log |
            Format-Table -AutoSize
    }

    try {
        $Ready = Invoke-RestMethod "http://127.0.0.1:8000/health/ready" -TimeoutSec 3
        Write-Host "API readiness: $($Ready.status)" -ForegroundColor Cyan
    }
    catch {
        Write-Host "API readiness: unavailable" -ForegroundColor Red
    }

    try {
        $Workers = Invoke-RestMethod "http://127.0.0.1:8000/health/workers" -TimeoutSec 3
        Write-Host "Workers: $($Workers.healthy_count)/$($Workers.expected_count) healthy" -ForegroundColor Cyan
        $Workers.workers |
            Select-Object name, status, heartbeat_age_seconds, consecutive_failures |
            Format-Table -AutoSize
    }
    catch {
        Write-Host "Worker diagnostics: unavailable" -ForegroundColor Red
    }
}

if ($Action -eq "Stop") {
    Stop-KnownProcesses
    Write-Host "ReclaimRail processes stopped." -ForegroundColor Green
    exit 0
}

if ($Action -eq "Status") {
    Show-ReclaimRailStatus
    exit 0
}

if ($Restart) {
    Stop-KnownProcesses
}
elseif (@(Read-RuntimeState | Where-Object {
    Test-TrackedProcessAlive -Entry $_
}).Count -gt 0) {
    throw "ReclaimRail already has tracked running processes. Use -Action Status or -Restart."
}

foreach ($CommandName in @("uv", "npm.cmd")) {
    if ($null -eq (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $CommandName"
    }
}

foreach ($RequiredFile in @("apps\api\.env", "apps\web\.env.local")) {
    $RequiredPath = Join-Path $RepoRoot $RequiredFile
    if (-not (Test-Path $RequiredPath)) {
        throw "Required environment file is missing: $RequiredPath"
    }
}

if (-not $SkipDocker) {
    if ($null -eq (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        throw "Docker is unavailable. Start Docker Desktop or use -SkipDocker."
    }
    Push-Location $RepoRoot
    try {
        docker compose up -d postgres redis
        if ($LASTEXITCODE -ne 0) { throw "Docker dependencies failed to start." }
    }
    finally {
        Pop-Location
    }
}

$Manifest = Read-ProcessManifest
foreach ($Entry in $Manifest.processes) {
    if ($null -eq $Entry.port) { continue }
    $PortOwner = Get-NetTCPConnection `
        -LocalPort ([int]$Entry.port) `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $PortOwner) {
        throw "Port $($Entry.port) required by $($Entry.name) is already used by PID $($PortOwner.OwningProcess)."
    }
}

Push-Location (Join-Path $RepoRoot "apps\api")
try {
    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $LogPath -Force | Out-Null
$StartedProcesses = @()

try {
    $StartedOrder = 0
    foreach ($Entry in $Manifest.processes) {
        $WorkingDirectory = Join-Path $RepoRoot $Entry.working_directory
        $StdoutPath = Join-Path $LogPath "$($Entry.name).out.log"
        $StderrPath = Join-Path $LogPath "$($Entry.name).err.log"
        $Executable = [string]$Entry.executable
        $Arguments = @($Entry.arguments | ForEach-Object { [string]$_ })

        Write-Host "Starting $($Entry.name)..." -ForegroundColor Cyan
        $Process = Start-Process `
            -FilePath $Executable `
            -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -PassThru

        $StartedProcesses += [pscustomobject]@{
            name = [string]$Entry.name
            pid = [int]$Process.Id
            process_name = $Process.ProcessName
            process_started_at_utc = $Process.StartTime.ToUniversalTime().ToString("o")
            started_order = $StartedOrder
            log = $StdoutPath
            error_log = $StderrPath
        }
        $StartedOrder += 1
    }

    [pscustomobject]@{
        schema_version = 1
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        processes = $StartedProcesses
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8

    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $Ready = Invoke-RestMethod "http://127.0.0.1:8000/health/ready" -TimeoutSec 2
            $Workers = Invoke-RestMethod "http://127.0.0.1:8000/health/workers" -TimeoutSec 2
            $Web = Invoke-WebRequest `
                "http://127.0.0.1:3000/payment-lab" `
                -TimeoutSec 2 `
                -UseBasicParsing
            $SystemReady = (
                $Ready.status -eq "ready" -and
                $Workers.healthy_count -eq $Workers.expected_count -and
                $Web.StatusCode -eq 200
            )
        }
        catch {
            $SystemReady = $false
        }
    } while (-not $SystemReady -and (Get-Date) -lt $Deadline)

    if (-not $SystemReady) {
        throw "ReclaimRail did not become healthy within $StartupTimeoutSeconds seconds. Inspect .runtime\logs."
    }
}
catch {
    if ($StartedProcesses.Count -gt 0) {
        [pscustomobject]@{ processes = $StartedProcesses } |
            ConvertTo-Json -Depth 5 |
            Set-Content -LiteralPath $StatePath -Encoding UTF8
        Stop-KnownProcesses
    }
    throw
}

Write-Host "ReclaimRail is ready." -ForegroundColor Green
Write-Host "Web: http://127.0.0.1:3000/payment-lab"
Write-Host "API: http://127.0.0.1:8000/health/ready"
Write-Host "Workers: http://127.0.0.1:8000/health/workers"
Write-Host "Queues: http://127.0.0.1:8000/health/queues"
Write-Host "Use: .\scripts\ReclaimRail-Local.ps1 -Action Status"
Write-Host "Use: .\scripts\ReclaimRail-Local.ps1 -Action Stop"
