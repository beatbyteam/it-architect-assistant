param(
  [string]$EnvFile = ".env.local",
  [switch]$PullModels,
  [switch]$SkipModelPull,
  [switch]$Gpu
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$gpuComposeFile = Join-Path $root "deploy\compose.local-production.gpu.yml"
$exampleEnv = Join-Path $root "deploy\local-production.env.example"
$targetEnv = Join-Path $root $EnvFile

$composeArgs = @("--env-file", $targetEnv, "-f", $composeFile)

if ($Gpu) {
  if (-not (Test-Path $gpuComposeFile)) {
    throw "GPU compose file not found: $gpuComposeFile"
  }

  $composeArgs += @("-f", $gpuComposeFile)
  Write-Host "Starting local release with NVIDIA GPU support"
} else {
  Write-Host "Starting local release without GPU override"
}

function Get-LocalEnvValue {
  param(
    [string]$Name,
    [string]$DefaultValue = ""
  )

  if (-not (Test-Path $targetEnv)) {
    return $DefaultValue
  }

  $prefix = "$Name="
  $match = Get-Content -Path $targetEnv | Where-Object { $_.StartsWith($prefix) } | Select-Object -Last 1
  if (-not $match) {
    return $DefaultValue
  }
  return $match.Substring($prefix.Length).Trim().Trim('"').Trim("'")
}

function Invoke-OllamaPull {
  param(
    [string]$ModelId
  )

  if ([string]::IsNullOrWhiteSpace($ModelId)) {
    return
  }

  Write-Host "Pulling Ollama model $ModelId"
  docker compose @composeArgs exec -T ollama ollama pull $ModelId
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

if (-not (Test-Path $targetEnv)) {
  Copy-Item -Path $exampleEnv -Destination $targetEnv
  Write-Host "Created $EnvFile from deploy/local-production.env.example"
}

docker compose @composeArgs up --build -d
Test-OllamaGpu

if (-not $SkipModelPull) {
  Invoke-OllamaPull -ModelId (Get-LocalEnvValue -Name "LLM_MODEL_ID" -DefaultValue "qwen2.5:7b-instruct")
  Invoke-OllamaPull -ModelId (Get-LocalEnvValue -Name "EMBEDDING_MODEL_ID" -DefaultValue "bge-m3")
  Invoke-OllamaPull -ModelId (Get-LocalEnvValue -Name "VISION_MODEL_ID")
}

docker compose @composeArgs ps
Write-Host "Local release is available at http://localhost:8080"

