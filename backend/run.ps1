Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating venv..."
  py -3.12 -m venv .venv
  & (Join-Path $PSScriptRoot ".venv\Scripts\pip.exe") install -r requirements.txt
}
if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
  Copy-Item (Join-Path $PSScriptRoot ".env.example") (Join-Path $PSScriptRoot ".env")
}
& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
