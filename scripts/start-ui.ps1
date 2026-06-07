# Start the SynchroniNote local UI (gradio) at http://127.0.0.1:7860
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-ui.ps1
#   or double-click scripts\start-ui.bat
$ErrorActionPreference = 'Stop'

$Port      = 7860
$ScriptDir = $PSScriptRoot
$Repo      = Split-Path -Parent $ScriptDir
$PythonDir = Join-Path $Repo 'python'
$PidFile   = Join-Path $ScriptDir '.synchroni-ui.pid'

# Already running? (port in use)
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Already running  ->  http://127.0.0.1:$Port"
    exit 0
}

if (-not (Test-Path $PythonDir)) {
    Write-Error "python dir not found: $PythonDir"
    exit 1
}

Write-Host "Starting SynchroniNote UI ..."
$proc = Start-Process -FilePath 'uv' -ArgumentList 'run', 'synchroni-note-ui' `
    -WorkingDirectory $PythonDir -WindowStyle Hidden -PassThru
Set-Content -Path $PidFile -Value $proc.Id -Encoding Ascii

Write-Host "Launched (PID $($proc.Id)). First run loads models (~10s)."
Write-Host "Open   ->  http://127.0.0.1:$Port   (the browser opens automatically)"
Write-Host "Stop   ->  scripts\stop-ui.bat   (or stop-ui.ps1)"
