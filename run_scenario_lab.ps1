$ErrorActionPreference = "Stop"
Set-Location "C:\Projects\PiperScenarioLab"

$python = "C:\Projects\Piper\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

& $python launcher.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "ScenarioLab launcher failed with exit code $LASTEXITCODE"
  Read-Host "Press Enter to close"
}
