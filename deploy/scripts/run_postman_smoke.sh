#!/usr/bin/env sh
set -eu

root_url="${1:-http://host.docker.internal:8080}"
root_url="${root_url%/}"
base_url="$root_url/api/v1"
root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -v "$root/postman:/etc/newman:ro" \
  postman/newman:alpine \
  run /etc/newman/it-architect-assistant-smoke.postman_collection.json \
  -e /etc/newman/local.postman_environment.json \
  --env-var "rootUrl=$root_url" \
  --env-var "baseUrl=$base_url"
