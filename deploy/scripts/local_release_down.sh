#!/usr/bin/env sh
set -eu

env_file=".env.local"
use_gpu="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --gpu)
      use_gpu="true"
      shift
      ;;
    *)
      env_file="$1"
      shift
      ;;
  esac
done

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
compose_file="$root/deploy/compose.local-production.yml"
gpu_compose_file="$root/deploy/compose.local-production.gpu.yml"
target_env="$root/$env_file"

compose() {
  if [ "$use_gpu" = "true" ]; then
    docker compose --env-file "$target_env" -f "$compose_file" -f "$gpu_compose_file" "$@"
  else
    docker compose --env-file "$target_env" -f "$compose_file" "$@"
  fi
}

if [ "$use_gpu" = "true" ]; then
  if [ ! -f "$gpu_compose_file" ]; then
    echo "GPU compose file not found: $gpu_compose_file" >&2
    exit 1
  fi

  echo "Stopping local release with NVIDIA GPU override"
else
  echo "Stopping local release without GPU override"
fi

compose down

echo "Local release is stopped"
