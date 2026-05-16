param(
  [string]$EnvFile = ".env.local",
  [switch]$PullModels,
  [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$exampleEnv = Join-Path $root "deploy\local-production.env.example"
$targetEnv = Join-Path $root $EnvFile

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
  docker compose --env-file $targetEnv -f $composeFile exec -T ollama ollama pull $ModelId
}

if (-not (Test-Path $targetEnv)) {
  Copy-Item -Path $exampleEnv -Destination $targetEnv
  Write-Host "Created $EnvFile from deploy/local-production.env.example"
}

docker compose --env-file $targetEnv -f $composeFile up --build -d

if (-not $SkipBootstrapKnowledge) {
  Wait-ApiReady
  docker compose --env-file $targetEnv -f $composeFile --profile bootstrap run --rm --no-deps knowledge-bootstrap
}

docker compose --env-file $targetEnv -f $composeFile ps
Write-Host "Local release is available at http://localhost:8080"
