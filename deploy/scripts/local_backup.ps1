param(
  [string]$EnvFile = ".env.local",
  [string]$OutputDir = "backups",
  [string]$ComposeFile = ""
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
$backupRoot = Resolve-ProjectPath $OutputDir

if (-not (Test-Path $targetEnv)) {
  throw "Env file not found: $targetEnv"
}
if (-not (Test-Path $ComposeFile)) {
  throw "Compose file not found: $ComposeFile"
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

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupId = "backup-$timestamp"
$backupDir = Join-Path $backupRoot $backupId
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "it-arch-backup-$timestamp"
$postgresDb = Get-LocalEnvValue -Name "POSTGRES_DB" -DefaultValue "it_arch_assistant"
$postgresUser = Get-LocalEnvValue -Name "POSTGRES_USER" -DefaultValue "postgres"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
  Write-Host "Creating PostgreSQL dump..."
  $dumpInContainer = "/tmp/it_arch_assistant_backup_$timestamp.dump"
  docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres pg_dump -U $postgresUser -d $postgresDb --format=custom --no-owner --no-privileges --file=$dumpInContainer
  $postgresContainer = docker compose --env-file $targetEnv -f $ComposeFile ps -q postgres
  if ([string]::IsNullOrWhiteSpace($postgresContainer)) {
    throw "Postgres container is not running"
  }
  docker cp "${postgresContainer}:$dumpInContainer" (Join-Path $backupDir "postgres.dump")
  docker compose --env-file $targetEnv -f $ComposeFile exec -T postgres rm -f $dumpInContainer

  Write-Host "Archiving deployment config..."
  $configDir = Join-Path $tempRoot "config"
  New-Item -ItemType Directory -Force -Path $configDir | Out-Null
  Copy-Item -Path (Join-Path $root "compose.yml") -Destination (Join-Path $configDir "compose.yml")
  Copy-Item -Path (Join-Path $root ".env.example") -Destination (Join-Path $configDir ".env.example")
  Copy-Item -Path $targetEnv -Destination (Join-Path $configDir (Split-Path $targetEnv -Leaf))
  Copy-Item -Path (Join-Path $root "deploy") -Destination (Join-Path $configDir "deploy") -Recurse
  Compress-Archive -Path $configDir -DestinationPath (Join-Path $backupDir "deployment_config.zip") -Force

  Write-Host "Archiving uploaded knowledge documents..."
  $backupDirForDocker = (Resolve-Path $backupDir).Path
  docker compose --env-file $targetEnv -f $ComposeFile run --rm --no-deps -T -v "${backupDirForDocker}:/backup" api sh -c "if [ -d /app/data/knowledge_uploads ]; then tar -C /app/data -czf /backup/knowledge_uploads.tgz knowledge_uploads; else mkdir -p /tmp/empty && tar -C /tmp/empty -czf /backup/knowledge_uploads.tgz .; fi"

  $gitRevision = "unknown"
  try {
    $gitRevision = (git -C $root rev-parse --short HEAD).Trim()
  } catch {
    $gitRevision = "unknown"
  }

  $manifest = [ordered]@{
    backup_id = $backupId
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    git_revision = $gitRevision
    postgres_db = $postgresDb
    compose_file = $ComposeFile
    env_file = $targetEnv
    contains = @("postgres.dump", "deployment_config.zip", "knowledge_uploads.tgz")
  }
  $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $backupDir "manifest.json") -Encoding UTF8

  $hashLines = @()
  foreach ($fileName in @("postgres.dump", "deployment_config.zip", "knowledge_uploads.tgz", "manifest.json")) {
    $filePath = Join-Path $backupDir $fileName
    $hash = Get-FileHash -Algorithm SHA256 -Path $filePath
    $hashLines += "$($hash.Hash.ToLowerInvariant())  $fileName"
  }
  $hashLines | Set-Content -Path (Join-Path $backupDir "SHA256SUMS") -Encoding UTF8

  Write-Host "Backup created: $backupDir"
} finally {
  if (Test-Path $tempRoot) {
    Remove-Item -Path $tempRoot -Recurse -Force
  }
}
