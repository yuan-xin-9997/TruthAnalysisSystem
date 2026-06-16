$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "data\server.pid"

if (Test-Path $PidFile) {
    $PidValue = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    Write-Output "PID file: $PidValue"
    if ($PidValue) {
        Get-Process -Id $PidValue -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime
    }
} else {
    Write-Output "No PID file found."
}

try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/settings/health" -UseBasicParsing -TimeoutSec 5
    Write-Output "HTTP: $($health.StatusCode)"
    Write-Output $health.Content
} catch {
    Write-Output "HTTP check failed: $($_.Exception.Message)"
}

