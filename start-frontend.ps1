Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path ".\node_modules\.bin\vite.cmd")) {
    npm ci
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

npm run dev
