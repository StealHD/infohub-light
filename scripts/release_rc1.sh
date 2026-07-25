#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${INTELISCOPE_DEPLOY_HOST:-vps-tokyo}"
REMOTE_BASE="${INTELISCOPE_DEPLOY_BASE:-/opt/inteliscope}"

usage() {
  echo "Usage: $0 prepare <sanitized-service.db> | promote <release-id> | rollback [release-id] | status"
}

require_clean_tree() {
  cd "$ROOT_DIR"
  if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    echo "Refusing to release a dirty working tree. Create an authorized release commit first." >&2
    exit 1
  fi
}

run_local_gates() {
  cd "$ROOT_DIR"
  ./.venv/bin/python scripts/test_gate.py run --mode release
}

validate_database_artifact() {
  local database="$1"
  ./.venv/bin/python - "$database" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"database artifact not found: {path}")
connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
try:
    checks = {
        "feed_v2": connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0],
        "sessions": connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "heartbeats": connection.execute(
            "SELECT COUNT(*) FROM worker_heartbeats"
        ).fetchone()[0],
        "active_jobs": connection.execute(
            "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0],
        "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_keys": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }
finally:
    connection.close()
if checks != {
    "feed_v2": 1,
    "sessions": 0,
    "heartbeats": 0,
    "active_jobs": 0,
    "integrity": "ok",
    "foreign_keys": 0,
}:
    raise SystemExit(f"database artifact failed validation: {checks}")
PY
}

prepare_release() {
  local database="$1"
  require_clean_tree
  run_local_gates
  require_clean_tree
  validate_database_artifact "$database"

  local revision version built_at release_id image platform expected_arch actual_arch image_revision
  local archive image_archive remote_archive remote_image_archive remote_database
  revision="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)"
  version="$(./.venv/bin/python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
  built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  release_id="rc1-$(date -u +%Y%m%dT%H%M%SZ)-${revision}"
  image="inteliscope-service:${release_id}"
  platform="${INTELISCOPE_DEPLOY_PLATFORM:-linux/amd64}"
  expected_arch="${platform#linux/}"
  archive="$(mktemp -t inteliscope-rc1.XXXXXX.tar.gz)"
  image_archive="$(mktemp -t inteliscope-rc1-image.XXXXXX.tar.gz)"
  remote_archive="/tmp/${release_id}.tar.gz"
  remote_image_archive="/tmp/${release_id}-image.tar.gz"
  remote_database="/tmp/${release_id}-service.db"
  trap 'rm -f "$archive" "$image_archive"' RETURN

  docker buildx build \
    --platform "$platform" \
    --load \
    --build-arg "INTELISCOPE_VERSION=$version" \
    --build-arg "INTELISCOPE_BUILD_REVISION=$revision" \
    --build-arg "INTELISCOPE_BUILT_AT=$built_at" \
    --tag "$image" \
    "$ROOT_DIR"
  actual_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
  image_revision="$(
    docker image inspect "$image" \
      --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
  )"
  [[ "$actual_arch" == "$expected_arch" ]] || {
    echo "local release image architecture mismatch: expected=$expected_arch actual=$actual_arch" >&2
    exit 1
  }
  [[ "$image_revision" == "$revision" ]] || {
    echo "local release image revision mismatch: expected=$revision actual=$image_revision" >&2
    exit 1
  }
  docker save "$image" | gzip -1 >"$image_archive"
  git -C "$ROOT_DIR" archive --format=tar.gz --output="$archive" HEAD
  scp "$archive" "$REMOTE_HOST:$remote_archive"
  scp "$image_archive" "$REMOTE_HOST:$remote_image_archive"
  scp "$database" "$REMOTE_HOST:$remote_database"

  ssh "$REMOTE_HOST" bash -s -- \
    "$REMOTE_BASE" "$release_id" "$image" "$version" "$revision" "$built_at" \
    "$remote_archive" "$remote_database" "$remote_image_archive" <<'REMOTE'
set -euo pipefail
base="$1"
release_id="$2"
image="$3"
version="$4"
revision="$5"
built_at="$6"
archive="$7"
database="$8"
image_archive="$9"
release_dir="$base/releases/$release_id"

if ! swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p "$base/releases" "$base/data" "$base/logs"
[[ ! -e "$release_dir" ]] || { echo "release already exists: $release_dir" >&2; exit 1; }
mkdir "$release_dir"
tar -xzf "$archive" -C "$release_dir" \
  --exclude='data' --exclude='data/*' \
  --exclude='logs' --exclude='logs/*' \
  --exclude='.env'
ln -s "$base/data" "$release_dir/data"
ln -s "$base/logs" "$release_dir/logs"
ln -s "$base/.env" "$release_dir/.env"

docker load -i "$image_archive"
loaded_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
loaded_revision="$(
  docker image inspect "$image" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
)"
[[ "$loaded_arch" == amd64 ]] || {
  echo "loaded release image architecture mismatch: $loaded_arch" >&2
  exit 1
}
[[ "$loaded_revision" == "$revision" ]] || {
  echo "loaded release image revision mismatch: $loaded_revision" >&2
  exit 1
}

[[ ! -e "$base/data/service.db" ]] || {
  echo "refusing to replace an existing remote service.db during RC1 bootstrap" >&2
  exit 1
}
install -m 600 "$database" "$base/data/.service.db.${release_id}.tmp"
mv "$base/data/.service.db.${release_id}.tmp" "$base/data/service.db"
rm -f "$archive" "$database" "$image_archive"

set_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$base/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$base/.env"
  else
    printf '%s=%s\n' "$key" "$value" >> "$base/.env"
  fi
}

set_env INTELISCOPE_IMAGE "$image"
set_env INTELISCOPE_VERSION "$version"
set_env INTELISCOPE_BUILD_REVISION "$revision"
set_env INTELISCOPE_BUILT_AT "$built_at"
set_env HORIZON_WEB_BIND 127.0.0.1
set_env HORIZON_WEB_PORT 18080
set_env HORIZON_REQUIRE_WORKER_FOR_READINESS false
set_env HORIZON_AUTH_SECURE_COOKIE false
set_env HORIZON_AUTH_SESSION_TTL_SECONDS 604800

cd "$base"
docker compose stop horizon-scheduler
cd "$release_dir"
docker compose -f docker-compose.light.yml up -d --no-build --force-recreate horizon-api
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18080/api/health/ready >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 60 ]] || { docker compose -f docker-compose.light.yml logs horizon-api; exit 1; }
  sleep 2
done
ln -sfn "$release_dir" "$base/current-staged"
REMOTE

  echo "Staged release: $release_id"
  echo "Open an SSH tunnel for staging checks: ssh -L 18080:127.0.0.1:18080 $REMOTE_HOST"
  echo "Promote after staging verification: $0 promote $release_id"
}

promote_release() {
  local release_id="$1"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" "$release_id" <<'REMOTE'
set -euo pipefail
base="$1"
release_id="$2"
release_dir="$base/releases/$release_id"
[[ -d "$release_dir" ]] || { echo "release not found: $release_dir" >&2; exit 1; }

set_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$base/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$base/.env"
  else
    printf '%s=%s\n' "$key" "$value" >> "$base/.env"
  fi
}

rollback_initial_cutover() {
  cd "$release_dir"
  docker compose -f docker-compose.light.yml stop horizon-worker horizon-api || true
  cd "$base"
  docker compose stop horizon-scheduler || true
  docker compose start horizon-web || true
}
trap rollback_initial_cutover ERR

cd "$base"
docker compose stop horizon-scheduler
docker compose stop horizon-web
set_env HORIZON_WEB_PORT 8080
set_env HORIZON_REQUIRE_WORKER_FOR_READINESS true
set_env HORIZON_AUTH_SECURE_COOKIE true

cd "$release_dir"
docker compose -f docker-compose.light.yml up -d --no-build --force-recreate horizon-api horizon-worker
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8080/api/health/ready >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 90 ]] || { docker compose -f docker-compose.light.yml logs horizon-api horizon-worker; exit 1; }
  sleep 2
done
revision="$(grep '^INTELISCOPE_BUILD_REVISION=' "$base/.env" | tail -n 1 | cut -d= -f2-)"
curl -fsS http://127.0.0.1:8080/api/health/live | grep -Fq "$revision"
if docker ps --format '{{.Names}}' | grep -qx 'horizon-scheduler'; then
  echo "legacy scheduler is still running" >&2
  exit 1
fi
ln -sfn "$release_dir" "$base/current"
rm -f "$base/current-staged"
trap - ERR
REMOTE
  echo "Promoted release: $release_id"
}

rollback_release() {
  local release_id="${1:-}"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" "$release_id" <<'REMOTE'
set -euo pipefail
base="$1"
release_id="$2"
if [[ -z "$release_id" && -L "$base/current" ]]; then
  release_id="$(basename "$(readlink "$base/current")")"
fi
[[ -n "$release_id" ]] || { echo "release id is required" >&2; exit 1; }
release_dir="$base/releases/$release_id"
if [[ -d "$release_dir" ]]; then
  cd "$release_dir"
  docker compose -f docker-compose.light.yml stop horizon-worker horizon-api
fi
cd "$base"
docker compose stop horizon-scheduler
docker compose start horizon-web
REMOTE
}

show_status() {
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" <<'REMOTE'
set -euo pipefail
base="$1"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
curl -fsS http://127.0.0.1:8080/api/health/live || true
curl -fsS http://127.0.0.1:8080/api/health/ready || true
if [[ -L "$base/current" ]]; then readlink "$base/current"; fi
REMOTE
}

command="${1:-}"
case "$command" in
  prepare)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    prepare_release "$2"
    ;;
  promote)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    promote_release "$2"
    ;;
  rollback)
    rollback_release "${2:-}"
    ;;
  status)
    show_status
    ;;
  *)
    usage
    exit 2
    ;;
esac
