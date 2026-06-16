$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "data\server.pid"
$ConfigFile = Join-Path $Root "config\app.json"
$Port = 8000

if (Test-Path $ConfigFile) {
    try {
        $Config = Get-Content -LiteralPath $ConfigFile -Raw | ConvertFrom-Json
        if ($Config.app.port) {
            $Port = [int]$Config.app.port
        }
    } catch {
        Write-Output "Could not read configured port, using default 8000."
    }
}

$PidsToStop = New-Object System.Collections.Generic.HashSet[int]

if (Test-Path $PidFile) {
    $PidValue = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    if ($PidValue -match '^\d+$') {
        [void]$PidsToStop.Add([int]$PidValue)
    }
} else {
    Write-Output "No PID file found."
}

$NetstatLines = netstat -ano | Select-String -Pattern "LISTENING"
foreach ($Line in $NetstatLines) {
    $Text = $Line.ToString()
    if ($Text -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
        [void]$PidsToStop.Add([int]$Matches[1])
    }
}

if ($PidsToStop.Count -eq 0) {
    Write-Output "No running service process found for port $Port."
    if (Test-Path $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    exit 0
}

$CurrentPid = $PID
foreach ($TargetPid in $PidsToStop) {
    if ($TargetPid -eq $CurrentPid) {
        continue
    }
    $Process = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if ($Process) {
        try {
            Stop-Process -Id $TargetPid -Force -ErrorAction Stop
            Write-Output "Stopped process PID=$TargetPid ($($Process.ProcessName))"
        } catch {
            Write-Output "Failed to stop PID=$TargetPid ($($Process.ProcessName)): $($_.Exception.Message)"
            Write-Output "If this process was started as administrator or by Codex with elevated permissions, run this script from an elevated terminal or restart it with start_service.cmd."
        }
    } else {
        Write-Output "No running process for PID=$TargetPid"
    }
}

Start-Sleep -Seconds 1
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/settings/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Output "Warning: service still responds on port $Port."
    exit 1
} catch {
    Write-Output "Service stopped on port $Port."
    if (Test-Path $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    exit 0
}
