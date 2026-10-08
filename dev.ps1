#Requires -Version 5.1
<#
.SYNOPSIS
    Local CI-equivalent dev/test runner for the smart-home repo. Runs ALL
    linting and testing of project code inside a Docker container that mirrors
    the GitHub CI toolchain. Never compile or run project tests on the Windows
    host.

.DESCRIPTION
    Subcommands:
      build            Build (or rebuild) the dev image from Dockerfile.citest.
      shell            Open an interactive bash shell in the container.
      run <cmd...>     Run a one-off command inside the container.
      ci [service]     Run the CI lint+test sequence for a service (default: dashboard),
                       reproducing ci.yml locally (ruff check, ruff format --check,
                       bandit, pytest). Pass a service dir name under services/ or
                       'dashboard' / 'pc-agent'.
      doctor           Print how to add a tool to the image.

    The script:
      (a) checks Docker is running and starts Docker Desktop if not, waiting for
          the daemon to respond;
      (b) builds the dev image if it is missing;
      (c) opens a shell or runs the given command inside the container;
      (d) documents how to add a tool (edit Dockerfile.citest + rebuild) instead
          of installing anything on the host.

.EXAMPLE
    .\dev.ps1 build
    .\dev.ps1 shell
    .\dev.ps1 run ruff check dashboard/src
    .\dev.ps1 ci dashboard
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('build', 'shell', 'run', 'ci', 'doctor', 'help')]
    [string]$Command = 'help',

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'

# --- Config ---------------------------------------------------------------
# This script, the compose file and the Dockerfile all live at the repo root.
# The repo to mount defaults to that root, so the whole thing works out of the
# box when run from a clone; override with SMART_HOME_REPO if needed.
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ComposeFile = Join-Path $ScriptDir 'docker-compose.citest.yml'
$ImageName   = 'smart-home-citest:local'
$RepoRoot    = if ($env:SMART_HOME_REPO) { $env:SMART_HOME_REPO } else { $ScriptDir }

# Make the bind-mount path available to compose (forward slashes for Docker).
$env:SMART_HOME_REPO = ($RepoRoot -replace '\\', '/')

# --- Helpers --------------------------------------------------------------
function Test-DockerRunning {
    try {
        docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Start-DockerDesktop {
    Write-Host '[dev] Docker daemon not responding. Starting Docker Desktop...' -ForegroundColor Yellow

    $candidates = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
    )
    $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $exe) {
        throw 'Docker Desktop.exe not found. Start Docker Desktop manually and retry.'
    }

    Start-Process -FilePath $exe | Out-Null

    $timeoutSec = 180
    $elapsed = 0
    Write-Host "[dev] Waiting up to $timeoutSec s for the Docker daemon..." -ForegroundColor Yellow
    while (-not (Test-DockerRunning)) {
        Start-Sleep -Seconds 3
        $elapsed += 3
        if ($elapsed -ge $timeoutSec) {
            throw "Docker daemon did not become ready within $timeoutSec s."
        }
        Write-Host '.' -NoNewline
    }
    Write-Host ''
    Write-Host '[dev] Docker daemon is ready.' -ForegroundColor Green
}

function Ensure-Docker {
    if (-not (Test-DockerRunning)) {
        Start-DockerDesktop
    }
}

function Test-ImageExists {
    docker image inspect $ImageName 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Invoke-Build {
    Write-Host "[dev] Building $ImageName from Dockerfile.citest ..." -ForegroundColor Cyan
    docker compose -f $ComposeFile build dev
    if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
    Write-Host '[dev] Build complete.' -ForegroundColor Green
}

function Ensure-Image {
    if (-not (Test-ImageExists)) {
        Write-Host '[dev] Dev image missing.' -ForegroundColor Yellow
        Invoke-Build
    }
}

function Invoke-InContainer {
    param([string[]]$ContainerArgs)
    # --rm: ephemeral; mounts the repo per docker-compose.citest.yml.
    docker compose -f $ComposeFile run --rm dev @ContainerArgs
    return $LASTEXITCODE
}

function Show-Doctor {
    @'
Add a tool to the dev image (NEVER install it on the Windows host):

  1. Edit Dockerfile.citest:
       - Python package  -> add it to the `pip install` block (pin a version).
       - System package  -> add it to the `apt-get install` block.
  2. Rebuild:            .\dev.ps1 build
  3. Use it:             .\dev.ps1 run <tool> ...

This keeps the host clean and the toolchain versioned in git-tracked files,
matching the "compile/test only in the container" rule. git / gh / ssh /
docker / robocopy still run on the host (pc-agent + Pi ops depend on them).
'@ | Write-Host
}

function Show-Help {
    @'
dev.ps1 - local CI-equivalent dev/test runner (all work happens in Docker)

  .\dev.ps1 build              Build / rebuild the dev image
  .\dev.ps1 shell              Interactive bash in the container
  .\dev.ps1 run <cmd...>       Run a one-off command in the container
  .\dev.ps1 ci [service]       Run CI lint+test for a service (default dashboard)
  .\dev.ps1 doctor             How to add a tool to the image

Env:
  SMART_HOME_REPO   Repo root to mount (default: this script's directory)
'@ | Write-Host
}

# Map a friendly service name to its source path (mirrors ci.yml).
function Resolve-ServicePath {
    param([string]$Service)
    switch ($Service) {
        'dashboard'         { return 'dashboard' }
        'ac-service'        { return 'services/ac-service' }
        'baby-gifts'        { return 'services/baby-gifts-service' }
        'portfolio-monitor' { return 'services/portfolio-monitor' }
        'vacaciones'        { return 'services/vacaciones-service' }
        'casita'            { return 'services/casita-suenos/fase3-app' }
        'valheim-admin'     { return 'services/valheim-admin' }
        'pc-agent'          { return 'tools/pc-agent' }
        default             { throw "Unknown service '$Service'. Known: dashboard, ac-service, baby-gifts, portfolio-monitor, vacaciones, casita, valheim-admin, pc-agent." }
    }
}

# Reproduce the CI lint+test sequence for one service inside the container.
function Invoke-Ci {
    param([string]$Service = 'dashboard')
    $path = Resolve-ServicePath -Service $Service
    $cov  = if ($Service -eq 'dashboard') {
        ' --cov=src --cov-report=term-missing --cov-fail-under=80'
    } elseif ($Service -eq 'ac-service') {
        ' --cov=src --cov-report=term-missing --cov-fail-under=80'
    } else { '' }

    # Services that import the shared smart_home_common library must install it
    # (editable) before pytest, mirroring the matching ci.yml job.
    $installCommon = if ($Service -in @('dashboard', 'ac-service', 'portfolio-monitor')) {
        "pip install -e libs/smart_home_common --quiet 2>/dev/null || true`n"
    } else { '' }

    # Build a bash -c pipeline that mirrors ci.yml steps for this service.
    $script = @"
set -e
echo '=== ruff check ==='
ruff check $path/src --output-format=github
echo '=== ruff format --check ==='
ruff format $path/src --check --diff
echo '=== bandit ==='
bandit -r $path/src -ll -ii --format txt
echo '=== pytest ==='
if [ -d "$path/tests" ] && find $path/tests -name 'test_*.py' | grep -q .; then
  pip install -r $path/requirements.txt --quiet 2>/dev/null || true
  $installCommon  cd $path && PYTHONPATH=src python -m pytest tests/ -v --tb=short$cov
else
  echo 'No tests found'
fi
"@
    return (Invoke-InContainer -ContainerArgs @('bash', '-c', $script))
}

# --- Dispatch -------------------------------------------------------------
switch ($Command) {
    'help'   { Show-Help; break }
    'doctor' { Show-Doctor; break }
    'build'  { Ensure-Docker; Invoke-Build; break }
    'shell'  {
        Ensure-Docker; Ensure-Image
        exit (Invoke-InContainer -ContainerArgs @('bash'))
    }
    'run'    {
        if (-not $Rest -or $Rest.Count -eq 0) { throw "Usage: .\dev.ps1 run <command...>" }
        Ensure-Docker; Ensure-Image
        exit (Invoke-InContainer -ContainerArgs $Rest)
    }
    'ci'     {
        Ensure-Docker; Ensure-Image
        $svc = if ($Rest -and $Rest.Count -ge 1) { $Rest[0] } else { 'dashboard' }
        exit (Invoke-Ci -Service $svc)
    }
}
