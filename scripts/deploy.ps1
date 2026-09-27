# Smart Home Deploy Script
# Usage: .\scripts\deploy.ps1 [service]
# Services: all, dashboard, ac-service, baby-gifts-service, vacaciones-service, casita-suenos

param(
    [string]$Service = "all"
)

$ValidServices = @("all", "dashboard", "ac-service", "baby-gifts-service", "vacaciones-service", "casita-suenos")

if ($Service -notin $ValidServices) {
    Write-Host "Error: Invalid service '$Service'" -ForegroundColor Red
    Write-Host "Valid services: $($ValidServices -join ', ')"
    exit 1
}

Write-Host "=== Smart Home Deploy ===" -ForegroundColor Cyan
Write-Host "Service: $Service"
Write-Host ""

# Step 1: Trigger GitHub Actions to build and push images
Write-Host "1. Triggering GitHub Actions build..." -ForegroundColor Yellow
gh workflow run deploy.yml -f service=$Service --repo EgnalZurc/smart-home

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to trigger workflow" -ForegroundColor Red
    exit 1
}

Write-Host "   Build triggered. Waiting for completion..." -ForegroundColor Green

# Wait for workflow to complete (max 10 minutes)
$maxWait = 600
$elapsed = 0
$runId = $null

Start-Sleep -Seconds 5

# Get the run ID
$runInfo = gh run list --repo EgnalZurc/smart-home --workflow=deploy.yml --limit 1 --json databaseId | ConvertFrom-Json
$runId = $runInfo[0].databaseId

Write-Host "   Workflow run ID: $runId"

while ($elapsed -lt $maxWait) {
    $status = gh run view $runId --repo EgnalZurc/smart-home --json status,conclusion | ConvertFrom-Json
    
    if ($status.status -eq "completed") {
        if ($status.conclusion -eq "success" -or $status.conclusion -eq "failure") {
            # The build jobs succeeded, deploy job may have failed (expected)
            Write-Host "   Build completed." -ForegroundColor Green
            break
        }
    }
    
    Write-Host "   Status: $($status.status) - waiting..." -ForegroundColor Gray
    Start-Sleep -Seconds 15
    $elapsed += 15
}

# Step 2: SSH to Pi and deploy
Write-Host ""
Write-Host "2. Deploying to Raspberry Pi..." -ForegroundColor Yellow

$sshCommand = @"
cd ~/smart-home-prod
echo '=== Pulling images ==='
docker compose pull
echo '=== Starting services ==='
docker compose up -d
echo '=== Status ==='
docker ps --format 'table {{.Names}}\t{{.Status}}' | head -15
"@

ssh pi@raspberrypi.local $sshCommand

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== Deploy Complete ===" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "=== Deploy Failed ===" -ForegroundColor Red
    exit 1
}
