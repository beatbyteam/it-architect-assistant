#!/usr/bin/env sh
set -eu

env_file=".env.local"
backup_dir=""
compose_file=""
yes="false"

usage() {
  cat <<'USAGE'
Usage: sh deploy/scripts/local_restore.sh --backup-dir backups/<backup-id> [--env-file .env.local] [--compose-file deploy/compose.local-production.yml] [--yes]

Restores:
  - PostgreSQL database from postgres.dump
  - uploaded knowledge documents from knowledge_uploads.tgz

The deployment_config.tgz file is kept in the backup for operator review and manual recovery of deployment settings.
This command replaces the current local database and uploaded knowledge documents.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --backup-dir)
      backup_dir="$2"
      shift 2
      ;;
    --compose-file)
      compose_file="$2"
      shift 2
      ;;
    --yes|-y)
      yes="true"
      shift
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

if [ -z "$backup_dir" ]; then
  echo "--backup-dir is required" >&2
  usage >&2
  exit 2
fi

case "$backup_dir" in
  /*) backup_dir="$backup_dir" ;;
  *) backup_dir="$root/$backup_dir" ;;
esac

if [ ! -f "$target_env" ]; then
  echo "Env file not found: $target_env" >&2
  exit 1
fi

if [ ! -f "$compose_file" ]; then
  echo "Compose file not found: $compose_file" >&2
  exit 1
fi

if [ ! -f "$backup_dir/postgres.dump" ]; then
  echo "PostgreSQL dump not found: $backup_dir/postgres.dump" >&2
  exit 1
fi

if [ ! -f "$backup_dir/knowledge_uploads.tgz" ]; then
  echo "Knowledge uploads archive not found: $backup_dir/knowledge_uploads.tgz" >&2
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

postgres_db="$(env_value POSTGRES_DB it_arch_assistant)"
postgres_user="$(env_value POSTGRES_USER postgres)"

if [ "$yes" != "true" ]; then
  printf 'This will replace local database "%s" and uploaded knowledge documents from "%s". Continue? [y/N] ' "$postgres_db" "$backup_dir"
  read answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Restore canceled."; exit 0 ;;
  esac
fi

echo "Starting PostgreSQL..."
docker compose --env-file "$target_env" -f "$compose_file" up -d postgres

echo "Stopping application services before restore..."
docker compose --env-file "$target_env" -f "$compose_file" stop api worker frontend gateway >/dev/null 2>&1 || true

echo "Restoring PostgreSQL database..."
docker compose --env-file "$target_env" -f "$compose_file" exec -T postgres \
  dropdb --if-exists -U "$postgres_user" "$postgres_db"
docker compose --env-file "$target_env" -f "$compose_file" exec -T postgres \
  createdb -U "$postgres_user" "$postgres_db"
docker compose --env-file "$target_env" -f "$compose_file" exec -T postgres \
  pg_restore -U "$postgres_user" -d "$postgres_db" --no-owner --no-privileges \
  < "$backup_dir/postgres.dump"

echo "Restoring uploaded knowledge documents..."
docker compose --env-file "$target_env" -f "$compose_file" run --rm --no-deps -T api \
  sh -c 'rm -rf /app/data/knowledge_uploads && mkdir -p /app/data && tar -C /app/data -xzf -' \
  < "$backup_dir/knowledge_uploads.tgz"

echo "Starting application services..."
docker compose --env-file "$target_env" -f "$compose_file" up -d

echo "Restore completed from: $backup_dir"
