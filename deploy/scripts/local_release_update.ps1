param(
  [string]$EnvFile = ".env.local"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$targetEnv = Join-Path $root $EnvFile

git pull --ff-only
docker compose --env-file $targetEnv -f $composeFile up --build -d --remove-orphans
docker compose --env-file $targetEnv -f $composeFile ps
Write-Host "Local release is updated at http://localhost:8080"
