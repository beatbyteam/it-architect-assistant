#!/usr/bin/env sh
set -eu

env_file=".env.local"
pull_models="${PULL_MODELS:-true}"
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
    --skip-model-pull)
      pull_models="false"
      shift
      ;;
    --pull-models)
      pull_models="true"
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
example_env="$root/deploy/local-production.env.example"
target_env="$root/$env_file"

compose() {
  if [ "$use_gpu" = "true" ]; then
    docker compose --env-file "$target_env" -f "$compose_file" -f "$gpu_compose_file" "$@"
  else
    docker compose --env-file "$target_env" -f "$compose_file" "$@"
  fi
}

env_value() {
  name="$1"
  default_value="$2"

  if [ ! -f "$target_env" ]; then
    printf '%s' "$default_value"
    return
  fi

  value="$(sed -n "s/^${name}=//p" "$target_env" | sed 's/\r$//' | tail -n 1)"

  if [ -n "$value" ]; then
    printf '%s' "$value" | sed "s/^['\"]//; s/['\"]$//"
  else
    printf '%s' "$default_value"
  fi
}

pull_ollama_model() {
  model_id="$1"
  if [ -z "$model_id" ]; then
    return
  fi
  echo "Pulling Ollama model $model_id"
  compose exec -T ollama ollama pull "$model_id"
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

if [ ! -f "$target_env" ]; then
  cp "$root/deploy/local-production.env.example" "$target_env"
  echo "Created $env_file from deploy/local-production.env.example"
fi

if [ "$use_gpu" = "true" ]; then
  if [ ! -f "$gpu_compose_file" ]; then
    echo "GPU compose file not found: $gpu_compose_file" >&2
    exit 1
  fi

  echo "Starting local release with NVIDIA GPU support"
else
  echo "Starting local release without GPU override"
fi

compose up --build -d
check_ollama_gpu

if [ "$pull_models" != "false" ]; then
  pull_ollama_model "$(env_value LLM_MODEL_ID qwen2.5:7b-instruct)"
  pull_ollama_model "$(env_value EMBEDDING_MODEL_ID bge-m3)"
  pull_ollama_model "$(env_value VISION_MODEL_ID '')"
fi

compose ps

echo "Local release is available at http://localhost:8080"
