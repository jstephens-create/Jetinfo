param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8501,
    [switch]$SetupOnly,
    [switch]$RebuildData
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot

# Keep the runtime, package cache, and environment inside this project.
$toolsDir = Join-Path $PSScriptRoot '.tools'
$uv = Join-Path $toolsDir 'uv.exe'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$env:UV_CACHE_DIR = Join-Path $toolsDir 'cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $toolsDir 'python'
$env:PYTHONUTF8 = '1'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    # PowerShell does not reliably throw for an external program's nonzero exit
    # code. Stop here so a failed ETL cannot be followed by training on stale data.
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $uv)) {
    Write-Host 'Downloading uv to set up a local Python runtime...'
    New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    $archive = Join-Path $toolsDir 'uv.zip'
    $architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
    $release = "https://github.com/astral-sh/uv/releases/latest/download/uv-$architecture-pc-windows-msvc.zip"
    Invoke-WebRequest -Uri $release -OutFile $archive -UseBasicParsing
    Expand-Archive -LiteralPath $archive -DestinationPath $toolsDir -Force
    Remove-Item -LiteralPath $archive
}

$pythonWorks = $false
$venvConfig = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
if ((Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath $venvConfig)) {
    $pythonHome = $null
    foreach ($line in Get-Content -LiteralPath $venvConfig) {
        if ($line -match '^\s*home\s*=\s*(.+?)\s*$') {
            $pythonHome = $Matches[1].Trim()
            break
        }
    }

    if ($pythonHome -and (Test-Path -LiteralPath (Join-Path $pythonHome 'python.exe'))) {
        & $python --version *> $null
        $pythonWorks = $LASTEXITCODE -eq 0
    }
}

if (-not $pythonWorks) {
    $venvArguments = @('venv', '--python', '3.12', '--managed-python')
    if (Test-Path -LiteralPath '.venv') {
        Write-Host 'Recreating the stale Python 3.12 environment...'
        $venvArguments += '--clear'
    } else {
        Write-Host 'Creating the Python 3.12 environment...'
    }
    $venvArguments += '.venv'
    Invoke-Checked -Program $uv -Arguments $venvArguments
}

Write-Host 'Checking project dependencies...'
Invoke-Checked -Program $uv -Arguments @('pip', 'install', '--python', $python, '-r', 'requirements.txt')

if (-not (Test-Path -LiteralPath 'data\raw\incidents_raw.csv')) {
    Invoke-Checked -Program $python -Arguments @('-m', 'src.generate_data')
}

$needsData = $RebuildData -or -not (Test-Path -LiteralPath 'data\processed\signal.db')
# Reuse prepared artifacts on normal launches. An explicit rebuild makes the
# dataset/model lifecycle visible instead of retraining as a side effect of login.
$needsModel = $needsData -or -not (Test-Path -LiteralPath 'models\sla_model.joblib') -or -not (Test-Path -LiteralPath 'models\metrics.json')
if ($needsData) {
    Write-Host 'Preparing the incident database...'
    Invoke-Checked -Program $python -Arguments @('-m', 'src.etl')
}
if ($needsModel) {
    Write-Host 'Training the risk model...'
    Invoke-Checked -Program $python -Arguments @('-m', 'src.train_model')
} else {
    Write-Host 'Using the prepared incident snapshot and model.'
}

if ($SetupOnly) {
    Write-Host 'Setup complete.'
    exit 0
}

Write-Host "Starting OKai at http://localhost:$Port (Ctrl+C to stop)..."
Invoke-Checked -Program $python -Arguments @(
    '-m', 'streamlit', 'run', 'app.py',
    '--server.address', '127.0.0.1', '--server.port', "$Port", '--server.headless', 'true'
)
