# install-service.ps1 — Install pc-agent as Windows Service using NSSM
# Run as Administrator

param(
    [switch]$Uninstall
)

$ServiceName = "pc-agent"
$AgentDir = $PSScriptRoot
$PythonExe = "$AgentDir\venv\Scripts\python.exe"
$MainScript = "$AgentDir\src\main.py"
$NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
$NssmDir = "$AgentDir\nssm"

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "Run this script as Administrator"
    exit 1
}

# Uninstall mode
if ($Uninstall) {
    Write-Host "Removing service: $ServiceName"
    & "$NssmDir\nssm.exe" stop $ServiceName 2>$null
    & "$NssmDir\nssm.exe" remove $ServiceName confirm
    Write-Host "Service removed."
    exit 0
}

# Download NSSM if not present
if (-not (Test-Path "$NssmDir\nssm.exe")) {
    Write-Host "Downloading NSSM..."
    New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
    $zipPath = "$AgentDir\nssm.zip"
    Invoke-WebRequest -Uri $NssmUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $AgentDir -Force
    Copy-Item "$AgentDir\nssm-2.24\win64\nssm.exe" "$NssmDir\nssm.exe" -Force
    Remove-Item "$AgentDir\nssm-2.24" -Recurse -Force
    Remove-Item $zipPath -Force
    Write-Host "NSSM installed to $NssmDir"
}

# Create venv if not exists
if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating virtual environment..."
    python -m venv "$AgentDir\venv"
    & "$AgentDir\venv\Scripts\pip.exe" install -r "$AgentDir\requirements.txt"
}

# Check .env exists
if (-not (Test-Path "$AgentDir\.env")) {
    Write-Warning ".env file not found! Copy .env.example to .env and configure it."
    Write-Warning "Continuing with installation, but service may not work correctly."
}

# Install service
Write-Host "Installing service: $ServiceName"

& "$NssmDir\nssm.exe" install $ServiceName $PythonExe $MainScript
& "$NssmDir\nssm.exe" set $ServiceName AppDirectory $AgentDir
& "$NssmDir\nssm.exe" set $ServiceName DisplayName "PC Agent - Smart Home"
& "$NssmDir\nssm.exe" set $ServiceName Description "Remote control agent for Valheim server and power profiles"
& "$NssmDir\nssm.exe" set $ServiceName Start SERVICE_AUTO_START
& "$NssmDir\nssm.exe" set $ServiceName AppStdout "$AgentDir\logs\stdout.log"
& "$NssmDir\nssm.exe" set $ServiceName AppStderr "$AgentDir\logs\stderr.log"
& "$NssmDir\nssm.exe" set $ServiceName AppRotateFiles 1
& "$NssmDir\nssm.exe" set $ServiceName AppRotateBytes 1048576

# Create logs directory
New-Item -ItemType Directory -Path "$AgentDir\logs" -Force | Out-Null

Write-Host ""
Write-Host "Service installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Commands:"
Write-Host "  Start:   nssm start $ServiceName"
Write-Host "  Stop:    nssm stop $ServiceName"
Write-Host "  Status:  nssm status $ServiceName"
Write-Host "  Logs:    Get-Content $AgentDir\logs\stdout.log -Tail 50"
Write-Host ""
Write-Host "Starting service..."
& "$NssmDir\nssm.exe" start $ServiceName

Start-Sleep -Seconds 2
$status = & "$NssmDir\nssm.exe" status $ServiceName
Write-Host "Service status: $status"
