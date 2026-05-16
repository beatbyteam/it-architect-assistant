#!/usr/bin/env sh
set -eu

env_file=".env.local"
bootstrap_knowledge="${BOOTSTRAP_KNOWLEDGE:-true}"
pull_models="${PULL_MODELS:-true}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
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
target_env="$root/$env_file"

env_value() {
  name="$1"
  default_value="$2"
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
  docker compose --env-file "$target_env" -f "$compose_file" exec -T ollama ollama pull "$model_id"
}

if [ ! -f "$target_env" ]; then
  cp "$root/deploy/local-production.env.example" "$target_env"
  echo "Created $env_file from deploy/local-production.env.example"
fi

docker compose --env-file "$target_env" -f "$compose_file" up --build -d

if [ "$pull_models" != "false" ]; then
  pull_ollama_model "$(env_value LLM_MODEL_ID qwen2.5:7b-instruct)"
  pull_ollama_model "$(env_value EMBEDDING_MODEL_ID bge-m3)"
fi

docker compose --env-file "$target_env" -f "$compose_file" ps
echo "Local release is available at http://localhost:8080"