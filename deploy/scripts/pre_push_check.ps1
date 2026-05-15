param(
  [switch]$SkipPostman
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$composeFile = Join-Path $root "deploy\compose.local-production.yml"
$envFile = Join-Path $root "deploy\local-production.env.example"

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Command
  )

  Write-Host ""
  Write-Host "==> $Name"
  & $Command
}

function Assert-NativeSuccess {
  param(
    [string]$Name
  )

  if ($LASTEXITCODE -ne 0) {
    throw "$Name failed with exit code $LASTEXITCODE"
  }
}

function Invoke-DockerRun {
  param(
    [string[]]$DockerArgs
  )

  docker run --rm @DockerArgs
  Assert-NativeSuccess "docker run"
}

Invoke-Step "Docker is available" {
  docker version
  Assert-NativeSuccess "docker version"
}

Invoke-Step "Compose files are valid" {
  docker compose -f (Join-Path $root "compose.yml") config | Out-Null
  Assert-NativeSuccess "docker compose config"
  docker compose --env-file $envFile -f $composeFile config | Out-Null
  Assert-NativeSuccess "docker compose local-production config"
}

Invoke-Step "Backend quality and tests" {
  Invoke-DockerRun @(
    "-e", "PYTHONDONTWRITEBYTECODE=1",
    "-v", "${root}:/workspace",
    "-w", "/workspace/backend",
    "python:3.12-slim",
    "sh", "-c",
    "pip install --disable-pip-version-check --no-cache-dir -e '.[dev]' PyYAML vulture >/tmp/pip.log && python -m ruff check app scripts && python -m mypy app/domain/services/canonical_read_helpers.py app/domain/services/knowledge/serializers.py app/domain/services/knowledge/update_diffing.py app/domain/services/verification/executor_contracts.py app/domain/services/verification/rule_engine.py app/domain/services/verification/rule_executors.py app/integrations/generation/llm_gateway.py app/integrations/generation/payload_normalization.py && python -m pytest app/tests -q --cov=app --cov-report=term-missing --cov-fail-under=70 && python scripts/check_config_surface.py && cd /workspace && python backend/scripts/check_module_guardrails.py"
  )
}

Invoke-Step "Frontend quality and tests" {
  Invoke-DockerRun @(
    "-v", "${root}/frontend:/app",
    "-v", "it_arch_mvp_frontend_node_modules:/app/node_modules",
    "-w", "/app",
    "node:22-alpine",
    "sh", "-c",
    "npm ci --silent && npm run lint && npm run typecheck && npm run test && npm run build"
  )
}

if (-not $SkipPostman) {
  Invoke-Step "Local release Postman/Newman smoke" {
    docker compose --env-file $envFile -f $composeFile up --build -d postgres redis api worker frontend gateway
    Assert-NativeSuccess "docker compose up for Postman smoke"

    try {
      $ready = $false
      for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
          Invoke-RestMethod -Uri "http://localhost:8080/api/v1/health/ready" -TimeoutSec 5 | Out-Null
          $ready = $true
          break
        } catch {
          Write-Host "Waiting for API readiness, attempt $attempt/60"
          Start-Sleep -Seconds 5
        }
      }

      if (-not $ready) {
        throw "API did not become ready at http://localhost:8080/api/v1/health/ready"
      }

      & (Join-Path $root "deploy\scripts\run_postman_smoke.ps1") -RootUrl "http://host.docker.internal:8080"
      if ($LASTEXITCODE -ne 0) {
        throw "run_postman_smoke.ps1 failed with exit code $LASTEXITCODE"
      }
    } finally {
      docker compose --env-file $envFile -f $composeFile logs --tail=200 api worker gateway
      docker compose --env-file $envFile -f $composeFile down --remove-orphans
    }
  }
}

Write-Host ""
Write-Host "Pre-push checks passed."
