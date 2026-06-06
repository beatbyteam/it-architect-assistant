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

check_ollama_gpu() {
  if [ "$use_gpu" != "true" ]; then
    return
  fi
  echo "Checking NVIDIA GPU visibility inside ollama"
  if compose exec -T ollama sh -lc 'test -e /dev/nvidiactl || test -e /dev/nvidia0'; then
    echo "NVIDIA GPU devices are visible inside ollama"
  else
    echo "WARNING: NVIDIA GPU devices are not visible inside ollama. Check NVIDIA driver, NVIDIA Container Toolkit, Docker GPU support and the compose plugin version." >&2
  fi
}

if [ "$use_gpu" = "true" ]; then
  if [ ! -f "$gpu_compose_file" ]; then
    echo "GPU compose file not found: $gpu_compose_file" >&2
    exit 1
  fi

  echo "Updating local release with NVIDIA GPU support"
else
  echo "Updating local release without GPU override"
fi

git pull --ff-only

compose up --build -d --remove-orphans
check_ollama_gpu
compose ps

echo "Local release is updated at http://localhost:8080"
