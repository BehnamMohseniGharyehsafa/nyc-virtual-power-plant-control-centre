$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Write-Host 'Create the environment first: python -m venv .venv'
    exit 1
}
& '.\.venv\Scripts\python.exe' -m app.main
