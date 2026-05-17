param(
  [Parameter(Mandatory = $true)]
  [string]$BackupDir,
  [string]$EnvFile = ".env.local",
  [string]$ComposeFile = "",
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

function Resolve-ProjectPath {
  param([string]$PathValue)
  if ([System.IO.Path]::IsPathRooted($PathValue)) {
    return $PathValue
  }
  return Join-Path $root $PathValue
}

if ([string]::IsNullOrWhiteSpace($ComposeFile)) {
  $ComposeFile = Join-Path $root "deploy\compose.local-production.yml"
} else {
  $ComposeFile = Resolve-ProjectPath $ComposeFile
}

$targetEnv = Resolve-ProjectPath $EnvFile
$backupDirPath = Resolve-ProjectPath $BackupDir

if (-not (Test-Path $targetEnv)) {
  throw "Env file not found: $targetEnv"
}
if (-not (Test-Path $ComposeFile)) {
  throw "Compose file not found: $ComposeFile"
}
if (-not (Test-Path (Join-Path $backupDirPath "postgres.dump"))) {
  throw "PostgreSQL dump not found: $(Join-Path $backupDirPath "postgres.dump")"
}
if (-not (Test-Path (Join-Path $backupDirPath "knowledge_uploads.tgz"))) {
  throw "Knowledge uploads archive not found: $(Join-Path $backupDirPath "knowledge_uploads.tgz")"
}

function Get-LocalEnvValue {
  param(
    [string]$Name,
    [string]$DefaultValue = ""
  )

  $prefix = "$Name="
  $match = Get-Content -Path $targetEnv | Where-Object { $_.StartsWith($prefix) } | Select-Object -Last 1
  if (-not $match) {
    return $DefaultValue
  }
  return $match.Substring($prefix.Length).Trim().Trim('"').Trim("'")
}

$postgresDb = Get-LocalEnvValue -Name "POSTGRES_DB" -DefaultValue "it_arch_assistant"
$postgresUser = Get-LocalEnvValue -Name "POSTGRES_USER" -DefaultValue "postgres"

if (-not $Yes) {
  $answer = Read-Host "This will replace local database '$postgresDb' and uploaded knowledge documents from '$backupDirPath'. Continue? [y/N]"
  if ($answer -notin @("y", "Y", "yes", "YES")) {
    Write-Host "Restore canceled."
    exit 0
  }
}

Write-Host "Starting PostgreSQL..."
docker compose --env-file $targetEnv -f $ComposeFile up -d postgres

Write-Host "Stopping application services before restore..."
try {
  docker compose --env-file $targetEnv -f $ComposeFile stop api worker frontend gateway | Out-Null
} catch {
  Write-Host "Some application services were not running."
}

Write-Host "Copying PostgreSQL dump into container..."
$dumpInContainer = "/tmp/it_arch_assistant_restore.dump"
$postgresContainer = docker compose --env-file $targetEnv -f $ComposeFile ps -q postgres
if ([string]::IsNullOrWhiteSpace($postgresContainer)) {
  throw "Postgres container is not running"
}
docker cp (Join-Path $backupDirPath "postgres.dump") "${postgresContainer}:$dumpInContainer"

Write-Host "Restoring PostgreSQL database..."
docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres dropdb --if-exists -U $postgresUser $postgresDb
docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres createdb -U $postgresUser $postgresDb
docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres pg_restore -U $postgresUser -d $postgresDb --no-owner --no-privileges $dumpInContainer
docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres rm -f $dumpInContainer

Write-Host "Restoring uploaded knowledge documents..."
$backupDirForDocker = (Resolve-Path $backupDirPath).Path
docker compose --env-file $targetEnv -f $ComposeFile run --rm --no-deps -T -v "${backupDirForDocker}:/backup:ro" api sh -c "rm -rf /app/data/knowledge_uploads && mkdir -p /app/data && tar -C /app/data -xzf /backup/knowledge_uploads.tgz"

Write-Host "Starting application services..."
docker compose --env-file $targetEnv -f $ComposeFile up -d

Write-Host "Restore completed from: $backupDirPath"
