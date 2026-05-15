#!/usr/bin/env sh
set -eu

skip_postman="${SKIP_POSTMAN:-false}"
root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
compose_file="$root/deploy/compose.local-production.yml"
env_file="$root/deploy/local-production.env.example"

step() {
  printf '\n==> %s\n' "$1"
}

step "Docker is available"
docker version

step "Compose files are valid"
docker compose -f "$root/compose.yml" config >/dev/null
docker compose --env-file "$env_file" -f "$compose_file" config >/dev/null

step "Backend quality and tests"
docker run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$root:/workspace" \
  -w /workspace/backend \
  python:3.12-slim \
  sh -c "pip install --disable-pip-version-check --no-cache-dir -e '.[dev]' PyYAML vulture >/tmp/pip.log && python -m ruff check app scripts && python -m mypy app/domain/services/canonical_read_helpers.py app/domain/services/knowledge/serializers.py app/domain/services/knowledge/update_diffing.py app/domain/services/verification/executor_contracts.py app/domain/services/verification/rule_engine.py app/domain/services/verification/rule_executors.py app/integrations/generation/llm_gateway.py app/integrations/generation/payload_normalization.py && python -m pytest app/tests -q --cov=app --cov-report=term-missing --cov-fail-under=70 && python scripts/check_config_surface.py && cd /workspace && python backend/scripts/check_module_guardrails.py"

step "Frontend quality and tests"
docker run --rm \
  -v "$root/frontend:/app" \
  -v it_arch_mvp_frontend_node_modules:/app/node_modules \
  -w /app \
  node:22-alpine \
  sh -c "npm ci --silent && npm run lint && npm run typecheck && npm run test && npm run build"

if [ "$skip_postman" != "true" ]; then
  step "Local release Postman/Newman smoke"
  docker compose --env-file "$env_file" -f "$compose_file" up --build -d postgres redis api worker frontend gateway
  trap 'docker compose --env-file "$env_file" -f "$compose_file" logs --tail=200 api worker gateway || true; docker compose --env-file "$env_file" -f "$compose_file" down --remove-orphans || true' EXIT

  ready=0
  for attempt in $(seq 1 60); do
    if docker run --rm --network host curlimages/curl:8.11.1 -fsS "http://127.0.0.1:8080/api/v1/health/ready"; then
      ready=1
      break
    fi
    echo "Waiting for API readiness, attempt $attempt/60"
    sleep 5
  done
  test "$ready" = "1"

  sh "$root/deploy/scripts/run_postman_smoke.sh"
fi

printf '\nPre-push checks passed.\n'
