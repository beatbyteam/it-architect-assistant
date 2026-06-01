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
  Write-Host "Updating local release with NVIDIA GPU support"
} else {
  Write-Host "Updating local release without GPU override"
}

function Test-OllamaGpu {
  if (-not $Gpu) {
    return
  }

  Write-Host "Checking NVIDIA GPU visibility inside ollama"
  docker compose @composeArgs exec -T ollama sh -lc "test -e /dev/nvidiactl || test -e /dev/nvidia0"
  if ($LASTEXITCODE -eq 0) {
    Write-Host "NVIDIA GPU devices are visible inside ollama"
  } else {
    Write-Warning "NVIDIA GPU devices are not visible inside ollama. Check NVIDIA driver, NVIDIA Container Toolkit, Docker GPU support and the compose plugin version."
  }
}

git pull --ff-only
docker compose @composeArgs up --build -d --remove-orphans
Test-OllamaGpu
docker compose @composeArgs ps
Write-Host "Local release is updated at http://localhost:8080"
