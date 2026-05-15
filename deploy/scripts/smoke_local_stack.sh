#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for smoke checks" >&2
  exit 1
fi

cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose config >/dev/null

docker compose up --build -d

for _ in $(seq 1 40); do
  if curl -fsS http://localhost:8000/api/v1/health/live >/dev/null; then
    break
  fi
  sleep 3
done

curl -fsS http://localhost:8000/api/v1/health/live >/dev/null
curl -fsS http://localhost:8080 >/dev/null

echo "smoke check passed"
