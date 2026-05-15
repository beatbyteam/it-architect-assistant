#!/usr/bin/env sh
set -eu

env_file="${1:-.env.local}"
root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
compose_file="$root/deploy/compose.local-production.yml"
target_env="$root/$env_file"

git pull --ff-only
docker compose --env-file "$target_env" -f "$compose_file" up --build -d --remove-orphans
docker compose --env-file "$target_env" -f "$compose_file" ps
echo "Local release is updated at http://localhost:8080"
