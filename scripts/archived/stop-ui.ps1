# Stop the SynchroniNote local UI (frees port 7860)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\stop-ui.ps1
#   or double-click scripts\stop-ui.bat
$Port      = 7860
$ScriptDir = $PSScriptRoot
$PidFile   = Join-Path $ScriptDir '.synchroni-ui.pid'
$stopped   = $false

# 1) Kill whatever is listening on the port (the actual server)
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
        Write-Host "Stopped PID $($c.OwningProcess) (port $Port)"
        $stopped = $true
    } catch {}
}

# 2) Kill the recorded launcher PID (uv), if any
if (Test-Path $PidFile) {
    $procId = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($procId) {
        try {
            Stop-Process -Id ([int]$procId) -Force -ErrorAction Stop
            Write-Host "Stopped PID $procId (launcher)"
            $stopped = $true
        } catch {}
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

if ($stopped) { Write-Host "SynchroniNote UI stopped." }
else { Write-Host "No running SynchroniNote UI found (port $Port is free)." }
