param(
  [string]$EnvFile = ".env.local",
  [switch]$Gpu
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$gpuComposeFile = Join-Path $root "deploy\compose.local-production.gpu.yml"
$targetEnv = Join-Path $root $EnvFile

$composeArgs = @("--env-file", $targetEnv, "-f", $composeFile)

if ($Gpu) {
  if (-not (Test-Path $gpuComposeFile)) {
    throw "GPU compose file not found: $gpuComposeFile"
  }

  $composeArgs += @("-f", $gpuComposeFile)
  Write-Host "Stopping local release with NVIDIA GPU support"
} else {
  Write-Host "Stopping local release without GPU override"
}

docker compose @composeArgs down

Write-Host "Local release is stopped"
