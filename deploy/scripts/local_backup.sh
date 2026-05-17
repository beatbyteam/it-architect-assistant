#!/usr/bin/env sh
set -eu

env_file=".env.local"
output_dir="backups"
compose_file=""

usage() {
  cat <<'USAGE'
Usage: sh deploy/scripts/local_backup.sh [--env-file .env.local] [--output-dir backups] [--compose-file deploy/compose.local-production.yml]

Creates a local backup with:
  - PostgreSQL custom dump
  - deployment config archive
  - uploaded knowledge documents archive

The backup contains sensitive data. Store it as an operator-only artifact.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --compose-file)
      compose_file="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

case "$env_file" in
  /*) target_env="$env_file" ;;
  *) target_env="$root/$env_file" ;;
esac

if [ -z "$compose_file" ]; then
  compose_file="$root/deploy/compose.local-production.yml"
else
  case "$compose_file" in
    /*) compose_file="$compose_file" ;;
    *) compose_file="$root/$compose_file" ;;
  esac
fi

case "$output_dir" in
  /*) backup_root="$output_dir" ;;
  *) backup_root="$root/$output_dir" ;;
esac

if [ ! -f "$target_env" ]; then
  echo "Env file not found: $target_env" >&2
  exit 1
fi

if [ ! -f "$compose_file" ]; then
  echo "Compose file not found: $compose_file" >&2
  exit 1
fi

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

timestamp="$(date '+%Y%m%d-%H%M%S')"
backup_id="backup-$timestamp"
backup_dir="$backup_root/$backup_id"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

postgres_db="$(env_value POSTGRES_DB it_arch_assistant)"
postgres_user="$(env_value POSTGRES_USER postgres)"

mkdir -p "$backup_dir"

echo "Creating PostgreSQL dump..."
docker compose --env-file "$target_env" -f "$compose_file" exec -T postgres \
  pg_dump -U "$postgres_user" -d "$postgres_db" --format=custom --no-owner --no-privileges \
  > "$backup_dir/postgres.dump"

echo "Archiving deployment config..."
mkdir -p "$tmp_dir/config"
cp "$root/compose.yml" "$tmp_dir/config/compose.yml"
cp "$root/.env.example" "$tmp_dir/config/.env.example"
cp "$target_env" "$tmp_dir/config/$(basename "$target_env")"
cp -R "$root/deploy" "$tmp_dir/config/deploy"
tar -C "$tmp_dir" -czf "$backup_dir/deployment_config.tgz" config

echo "Archiving uploaded knowledge documents..."
docker compose --env-file "$target_env" -f "$compose_file" run --rm --no-deps -T api \
  sh -c 'if [ -d /app/data/knowledge_uploads ]; then tar -C /app/data -czf - knowledge_uploads; else mkdir -p /tmp/empty && tar -C /tmp/empty -czf - .; fi' \
  > "$backup_dir/knowledge_uploads.tgz"

git_revision="$(git -C "$root" rev-parse --short HEAD 2>/dev/null || printf 'unknown')"
cat > "$backup_dir/manifest.json" <<MANIFEST
{
  "backup_id": "$backup_id",
  "created_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "git_revision": "$git_revision",
  "postgres_db": "$postgres_db",
  "compose_file": "$compose_file",
  "env_file": "$target_env",
  "contains": [
    "postgres.dump",
    "deployment_config.tgz",
    "knowledge_uploads.tgz"
  ]
}
MANIFEST

(
  cd "$backup_dir"
  shasum -a 256 postgres.dump deployment_config.tgz knowledge_uploads.tgz manifest.json > SHA256SUMS
)

echo "Backup created: $backup_dir"
