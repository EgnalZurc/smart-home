<#
.SYNOPSIS
  Minimal service registration validator (SSOT: docker-compose.prod.yml + service.toml).
.DESCRIPTION
  Checks basic consistency: manifests present, required keys (simple regex TOML parsing for our schema),
  declared keys vs docker-compose.prod.yml services, own-directory/code_path, and coverage.
  Manifests: services/*/service.toml and known extra locations (e.g. dashboard/service.toml).
  Does not replace test_catalogue_coherence.py or CI; this is a fast local/pre-check.
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = '',
  [switch]$Strict  # also fail on warnings
)

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot }
elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
else { (Get-Location).Path }
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path }

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TomlValue {
  param([string]$Text, [string]$Section, [string]$Key)
  # Minimal parser for our schema: find [section], then key = "..." | true/false | number.
  $sectionRx = '(?ms)^\[' + [regex]::Escape($Section) + '\]\s*(.*?)(?=^\[|\z)'
  $m = [regex]::Match($Text, $sectionRx)
  if (-not $m.Success) { return $null }
  $body = $m.Groups[1].Value
  $keyRx = '(?m)^\s*' + [regex]::Escape($Key) + '\s*=\s*(?:"([^"]*)"|(true|false)|(-?\d+))\s*(?:#.*)?$'
  $k = [regex]::Match($body, $keyRx)
  if (-not $k.Success) { return $null }
  if ($k.Groups[1].Success) { return $k.Groups[1].Value }
  if ($k.Groups[2].Success) { return [bool]::Parse($k.Groups[2].Value) }
  if ($k.Groups[3].Success) { return [int]$k.Groups[3].Value }
  return $null
}

function Get-ComposeServiceKeys {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { throw "Not found: $Path" }
  $keys = @()
  $inServices = $false
  foreach ($line in Get-Content -LiteralPath $Path) {
    # Parse only the top-level services: block (avoid networks/volumes keys).
    if ($line -match '^services:\s*(#.*)?$') { $inServices = $true; continue }
    if ($inServices -and $line -match '^[a-zA-Z]') { $inServices = $false }
    if (-not $inServices) { continue }
    if ($line -match '^  ([a-z0-9][a-z0-9_-]*):\s*(#.*)?$') { $keys += $Matches[1] }
  }
  return $keys | Sort-Object -Unique
}

function Register-Manifest {
  param(
    [string]$Label,
    [string]$ManifestPath,
    [string]$ExpectedKey, # if set (services/<dir>), warn when key differs
    [hashtable]$ManifestKeys,
    [System.Collections.Generic.List[string]]$Errors,
    [System.Collections.Generic.List[string]]$Warnings,
    [string]$RepoRoot
  )
  $text = Get-Content -LiteralPath $ManifestPath -Raw
  $key = Get-TomlValue -Text $text -Section 'service' -Key 'key'
  $class = Get-TomlValue -Text $text -Section 'service' -Key 'class'
  $health = Get-TomlValue -Text $text -Section 'service' -Key 'health_path'
  $codePath = Get-TomlValue -Text $text -Section 'service' -Key 'code_path'

  if (-not $key) { $Errors.Add("${Label}: missing [service].key"); return }
  if ($ExpectedKey -and $key -ne $ExpectedKey) {
    $Warnings.Add("${Label}: [service].key='$key' differs from directory name '$ExpectedKey'")
  }
  if ($class -notin @('app','infrastructure','wrapper','external')) {
    $Errors.Add("${Label}: invalid or missing [service].class ('$class')")
  }
  if ($class -eq 'app' -and -not $health) { $Warnings.Add("${Label}: app missing [service].health_path") }
  if ($codePath) {
    $resolved = Join-Path $RepoRoot $codePath
    if (-not (Test-Path -LiteralPath $resolved)) { $Warnings.Add("${Label}: code_path does not exist: $codePath") }
  } elseif ($class -in @('app','wrapper')) {
    $Warnings.Add("${Label}: missing [service].code_path (each service must declare its own directory)")
  }
  if ($ManifestKeys.ContainsKey($key)) { $Errors.Add("Duplicate service.key: '$key' ($Label)") }
  $ManifestKeys[$key] = @{ Path = $ManifestPath; Class = $class; Label = $Label }
}

$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
$infos = New-Object System.Collections.Generic.List[string]

$composePath = Join-Path $RepoRoot 'docker-compose.prod.yml'
$servicesDir = Join-Path $RepoRoot 'services'
$composeKeys = @()
try { $composeKeys = Get-ComposeServiceKeys -Path $composePath } catch { $errors.Add($_.Exception.Message) }

$manifestKeys = @{}

# 1) Manifests in services/ directories
if (Test-Path -LiteralPath $servicesDir) {
  Get-ChildItem -LiteralPath $servicesDir -Directory | Where-Object { $_.Name -ne '_template' } | ForEach-Object {
    $dir = $_
    $manifest = Join-Path $dir.FullName 'service.toml'
    $label = "services/$($dir.Name)/service.toml"
    if (-not (Test-Path -LiteralPath $manifest)) {
      $warnings.Add("Missing service.toml: services/$($dir.Name)/ (incremental migration: add when touching the service)")
      return
    }
    Register-Manifest -Label $label -ManifestPath $manifest -ExpectedKey $dir.Name -ManifestKeys $manifestKeys -Errors $errors -Warnings $warnings -RepoRoot $RepoRoot
  }
}

# 2) Extra manifests (components with their own directory outside services/)
$extraManifests = @(
  @{ Label = 'dashboard/service.toml'; Path = (Join-Path $RepoRoot 'dashboard/service.toml'); ExpectedKey = '' }
)
foreach ($extra in $extraManifests) {
  if (Test-Path -LiteralPath $extra.Path) {
    Register-Manifest -Label $extra.Label -ManifestPath $extra.Path -ExpectedKey $extra.ExpectedKey -ManifestKeys $manifestKeys -Errors $errors -Warnings $warnings -RepoRoot $RepoRoot
  }
}

# 3) Basic manifest <-> compose consistency
foreach ($k in $manifestKeys.Keys) {
  $meta = $manifestKeys[$k]
  if ($meta.Class -in @('external')) { continue }
  if ($composeKeys.Count -gt 0 -and $k -notin $composeKeys) {
    $warnings.Add("service.toml '$k' ($($meta.Label)) is not present as a service in docker-compose.prod.yml (different name, or dev/wrapper only?)")
  }
}

# 4) Compose coverage (informational)
$knownInfraNoManifest = @('mosquitto','redis','zigbee2mqtt','nginx','docker-socket-proxy')
foreach ($ck in $composeKeys) {
  if ($manifestKeys.ContainsKey($ck)) { continue }
  if ($ck -in $knownInfraNoManifest) {
    $infos.Add("Compose '${ck}': external/support infrastructure without service.toml (OK for now).")
  } else {
    $infos.Add("Compose '${ck}': no registered service.toml (add a manifest or declare its location per the standard).")
  }
}

# 5) Summary
Write-Host "== validate-services =="
Write-Host "Repo: $RepoRoot"
Write-Host "compose.prod services: $($composeKeys.Count) | service.toml: $($manifestKeys.Count)"
Write-Host "Rule: every service/component with its own integration must have its own directory + service.toml (incremental migration)."
if ($infos.Count)    { Write-Host "`nInfo:" -ForegroundColor Cyan;   $infos    | ForEach-Object { Write-Host "  - $_" -ForegroundColor Cyan } }
if ($warnings.Count) { Write-Host "`nWarnings:" -ForegroundColor Yellow; $warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow } }
if ($errors.Count)   { Write-Host "`nErrors:" -ForegroundColor Red;    $errors   | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red } }

if ($errors.Count -gt 0) { exit 1 }
if ($Strict -and $warnings.Count -gt 0) { exit 2 }
Write-Host "`nOK (minimal validation)." -ForegroundColor Green
exit 0
