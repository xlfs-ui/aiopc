$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    if (-not $env:CONDA_PREFIX) {
        throw 'No active Conda environment. Create and activate your environment first, then run this command again.'
    }
    if ($env:CONDA_DEFAULT_ENV -eq 'base') {
        throw 'Activate a dedicated Conda environment first. Do not install project dependencies in base.'
    }
    $projectPython = Join-Path $env:CONDA_PREFIX 'python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        throw 'The active Conda environment has no Python executable.'
    }

    Write-Host "Using active Conda environment: $env:CONDA_PREFIX"
    Write-Host "Installing backend dependencies with Python: $projectPython"
    & $projectPython -m pip install -r backend/requirements.txt -c backend/requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

    Write-Host 'Dependencies installed in the active Conda environment.'
    Write-Host 'Start both services from the project root with: pnpm dev'
} finally {
    Pop-Location
}
