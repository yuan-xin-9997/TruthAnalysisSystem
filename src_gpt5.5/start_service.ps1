$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Out = Join-Path $Root "data\server.out.log"
$Err = Join-Path $Root "data\server.err.log"
$PidFile = Join-Path $Root "data\server.pid"

if (-not (Test-Path (Join-Path $Root "data"))) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
}

try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/settings/health" -UseBasicParsing -TimeoutSec 2
    if ($health.StatusCode -eq 200) {
        Write-Output "Service is already running: http://127.0.0.1:8000"
        exit 0
    }
} catch {
}

$env:PYTHONPATH = $Root
$Process = Start-Process `
    -FilePath "python" `
    -ArgumentList @("-m", "app.main", "--config", "$Root\config\app.json") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Out `
    -RedirectStandardError $Err `
    -PassThru

Start-Sleep -Seconds 3
$Process.Id | Set-Content -LiteralPath $PidFile

try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/settings/health" -UseBasicParsing -TimeoutSec 10
    Write-Output "Service started. PID=$($Process.Id)"
    Write-Output "Local URL: http://127.0.0.1:8000"
    Write-Output $health.Content
} catch {
    Write-Output "Service did not respond after start. Check logs:"
    Write-Output $Err
    if (Test-Path $Err) {
        Get-Content -LiteralPath $Err -Tail 80
    }
    exit 1
}

