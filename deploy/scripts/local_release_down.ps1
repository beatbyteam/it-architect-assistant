param(
  [string]$EnvFile = ".env.local"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$targetEnv = Join-Path $root $EnvFile

docker compose --env-file $targetEnv -f $composeFile down
