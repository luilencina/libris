Set-Location "$PSScriptRoot\backend"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created backend\.env. Add your Gemini API key to enable Cloud API mode."
}

& $python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
