<# 
.SYNOPSIS
  Validador mínimo de registro de servicios (SSOT: docker-compose.prod.yml + services/*/service.toml).
.DESCRIPTION
  Comprueba coherencia básica: manifiestos presentes, claves obligatorias (parseo simple TOML por regex),
  keys declaradas vs servicios en docker-compose.prod.yml, directorio propio/code_path, y avisos de alta incompleta.
  No reemplaza test_catalogue_coherence.py ni CI; es una comprobación rápida local/previa.
#>
[CmdletBinding()]
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [switch]$Strict  # falla también por avisos
)

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
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^  ([a-z0-9][a-z0-9_-]*):\s*(#.*)?$') { $keys += $Matches[1] }
  }
  return $keys | Sort-Object -Unique
}

$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

$composePath = Join-Path $RepoRoot 'docker-compose.prod.yml'
$servicesDir = Join-Path $RepoRoot 'services'
$composeKeys = @()
try { $composeKeys = Get-ComposeServiceKeys -Path $composePath } catch { $errors.Add($_.Exception.Message) }

# 1) Manifiestos por directorio en services/
$manifestKeys = @{}
if (Test-Path -LiteralPath $servicesDir) {
  Get-ChildItem -LiteralPath $servicesDir -Directory | Where-Object { $_.Name -ne '_template' } | ForEach-Object {
    $dir = $_
    $manifest = Join-Path $dir.FullName 'service.toml'
    if (-not (Test-Path -LiteralPath $manifest)) {
      $warnings.Add("Falta service.toml: services/$($dir.Name)/ (migración incremental: añadir al tocar el servicio)")
      return
    }
    $text = Get-Content -LiteralPath $manifest -Raw
    $key = Get-TomlValue -Text $text -Section 'service' -Key 'key'
    $class = Get-TomlValue -Text $text -Section 'service' -Key 'class'
    $health = Get-TomlValue -Text $text -Section 'service' -Key 'health_path'
    $codePath = Get-TomlValue -Text $text -Section 'service' -Key 'code_path'

    if (-not $key) { $errors.Add("$($dir.Name)/service.toml: falta [service].key"); return }
    if ($key -ne $dir.Name) { $warnings.Add("$($dir.Name)/service.toml: [service].key='$key' difiere del nombre de carpeta '$($dir.Name)'") }
    if ($class -notin @('app','infrastructure','wrapper','external')) {
      $errors.Add("$($dir.Name)/service.toml: [service].class inválida o ausente ('$class')")
    }
    if ($class -eq 'app' -and -not $health) { $warnings.Add("$($dir.Name)/service.toml: app sin [service].health_path") }
    if ($codePath) {
      $resolved = Join-Path $RepoRoot $codePath
      if (-not (Test-Path -LiteralPath $resolved)) { $warnings.Add("$($dir.Name)/service.toml: code_path no existe: $codePath") }
    } elseif ($class -in @('app','wrapper')) {
      $warnings.Add("$($dir.Name)/service.toml: falta [service].code_path (cada servicio debe declarar su directorio propio)")
    }
    if ($manifestKeys.ContainsKey($key)) { $errors.Add("service.key duplicada: '$key'") }
    $manifestKeys[$key] = @{ Path = $manifest; Class = $class; Dir = $dir.Name }
  }
}

# 2) Manifiestos cuya key debería existir en compose prod (salvo external)
foreach ($k in $manifestKeys.Keys) {
  $meta = $manifestKeys[$k]
  if ($meta.Class -in @('external')) { continue }
  if ($composeKeys.Count -gt 0 -and $k -notin $composeKeys -and $meta.Dir -notin $composeKeys) {
    $warnings.Add("service.toml '$k' no aparece como servicio en docker-compose.prod.yml (¿nombre distinto, o solo dev/wrapper?)")
  }
}

# 3) Resumen
Write-Host "== validate-services =="
Write-Host "Repo: $RepoRoot"
Write-Host "compose.prod services: $($composeKeys.Count) | service.toml: $($manifestKeys.Count)"
Write-Host "Regla: cada servicio debe tener su propio directorio + service.toml (migración incremental para existentes)."
if ($warnings.Count) { Write-Host "`nAvisos:" -ForegroundColor Yellow; $warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow } }
if ($errors.Count)   { Write-Host "`nErrores:" -ForegroundColor Red;    $errors   | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red } }

if ($errors.Count -gt 0) { exit 1 }
if ($Strict -and $warnings.Count -gt 0) { exit 2 }
Write-Host "`nOK (validación mínima)." -ForegroundColor Green
exit 0
