<# 
.SYNOPSIS
  Validador mínimo de registro de servicios (SSOT: docker-compose.prod.yml + service.toml).
.DESCRIPTION
  Comprueba coherencia básica: manifiestos presentes, claves obligatorias (parseo simple TOML por regex),
  keys declaradas vs servicios en docker-compose.prod.yml, directorio propio/code_path, y cobertura.
  Manifiestos: services/*/service.toml y rutas extra conocidas (p. ej. dashboard/service.toml).
  No reemplaza test_catalogue_coherence.py ni CI; es una comprobación rápida local/previa.
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = '',
  [switch]$Strict  # falla también por avisos
)

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot }
elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
else { (Get-Location).Path }
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $scriptDir '..')).Path }

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-TomlValue {
  param([string]$Text, [string]$Section, [string]$Key)
  # Parser mínimo para nuestro esquema: busca [section] y luego key = "..." | true/false | número.
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
  if (-not (Test-Path -LiteralPath $Path)) { throw "No existe: $Path" }
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

  if (-not $key) { $Errors.Add("${Label}: falta [service].key"); return }
  if ($ExpectedKey -and $key -ne $ExpectedKey) {
    $Warnings.Add("${Label}: [service].key='$key' difiere del nombre de carpeta '$ExpectedKey'")
  }
  if ($class -notin @('app','infrastructure','wrapper','external')) {
    $Errors.Add("${Label}: [service].class inválida o ausente ('$class')")
  }
  if ($class -eq 'app' -and -not $health) { $Warnings.Add("${Label}: app sin [service].health_path") }
  if ($codePath) {
    $resolved = Join-Path $RepoRoot $codePath
    if (-not (Test-Path -LiteralPath $resolved)) { $Warnings.Add("${Label}: code_path no existe: $codePath") }
  } elseif ($class -in @('app','wrapper')) {
    $Warnings.Add("${Label}: falta [service].code_path (cada servicio debe declarar su directorio propio)")
  }
  if ($ManifestKeys.ContainsKey($key)) { $Errors.Add("service.key duplicada: '$key' ($Label)") }
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

# 1) Manifiestos por directorio en services/
if (Test-Path -LiteralPath $servicesDir) {
  Get-ChildItem -LiteralPath $servicesDir -Directory | Where-Object { $_.Name -ne '_template' } | ForEach-Object {
    $dir = $_
    $manifest = Join-Path $dir.FullName 'service.toml'
    $label = "services/$($dir.Name)/service.toml"
    if (-not (Test-Path -LiteralPath $manifest)) {
      $warnings.Add("Falta service.toml: services/$($dir.Name)/ (migración incremental: añadir al tocar el servicio)")
      return
    }
    Register-Manifest -Label $label -ManifestPath $manifest -ExpectedKey $dir.Name -ManifestKeys $manifestKeys -Errors $errors -Warnings $warnings -RepoRoot $RepoRoot
  }
}

# 2) Manifiestos extra (componentes con directorio propio fuera de services/)
$extraManifests = @(
  @{ Label = 'dashboard/service.toml'; Path = (Join-Path $RepoRoot 'dashboard/service.toml'); ExpectedKey = '' }
)
foreach ($extra in $extraManifests) {
  if (Test-Path -LiteralPath $extra.Path) {
    Register-Manifest -Label $extra.Label -ManifestPath $extra.Path -ExpectedKey $extra.ExpectedKey -ManifestKeys $manifestKeys -Errors $errors -Warnings $warnings -RepoRoot $RepoRoot
  }
}

# 3) Coherencia básica manifiestos <-> compose
foreach ($k in $manifestKeys.Keys) {
  $meta = $manifestKeys[$k]
  if ($meta.Class -in @('external')) { continue }
  if ($composeKeys.Count -gt 0 -and $k -notin $composeKeys) {
    $warnings.Add("service.toml '$k' ($($meta.Label)) no aparece como servicio en docker-compose.prod.yml (¿nombre distinto, o solo dev/wrapper?)")
  }
}

# 4) Cobertura compose (informativo)
$knownInfraNoManifest = @('mosquitto','redis','zigbee2mqtt','nginx','docker-socket-proxy')
foreach ($ck in $composeKeys) {
  if ($manifestKeys.ContainsKey($ck)) { continue }
  if ($ck -in $knownInfraNoManifest) {
    $infos.Add("Compose '$ck': infraestructura externa/soporte sin service.toml (OK por ahora).")
  } else {
    $infos.Add("Compose '$ck': sin service.toml registrado (añadir manifiesto o declarar ubicación según estándar).")
  }
}

# 5) Resumen
Write-Host "== validate-services =="
Write-Host "Repo: $RepoRoot"
Write-Host "compose.prod services: $($composeKeys.Count) | service.toml: $($manifestKeys.Count)"
Write-Host "Regla: cada servicio/componente con integración propia debe tener su directorio + service.toml (migración incremental)."
if ($infos.Count)    { Write-Host "`nInfo:" -ForegroundColor Cyan;   $infos    | ForEach-Object { Write-Host "  - $_" -ForegroundColor Cyan } }
if ($warnings.Count) { Write-Host "`nAvisos:" -ForegroundColor Yellow; $warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow } }
if ($errors.Count)   { Write-Host "`nErrores:" -ForegroundColor Red;    $errors   | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red } }

if ($errors.Count -gt 0) { exit 1 }
if ($Strict -and $warnings.Count -gt 0) { exit 2 }
Write-Host "`nOK (validación mínima)." -ForegroundColor Green
exit 0
