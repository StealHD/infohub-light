#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNTIME_ROOT_ARGUMENT=""
DRY_RUN="false"

usage() {
  cat <<'EOF'
Usage: ./scripts/up-latest.sh [--runtime-root ABSOLUTE_PATH] [--dry-run]

Build from the Worktree that owns this script, then recreate the local API and
Worker with the primary checkout's .env, data, and logs. The runtime root is
resolved from Git's common directory unless --runtime-root is provided.
EOF
}

fail() {
  printf 'up-latest: %s\n' "$1" >&2
  exit 1
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      [[ "$#" -ge 2 ]] || fail "--runtime-root requires an absolute path"
      RUNTIME_ROOT_ARGUMENT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

if [[ -n "$RUNTIME_ROOT_ARGUMENT" ]]; then
  [[ "$RUNTIME_ROOT_ARGUMENT" == /* ]] || fail "--runtime-root must be an absolute path"
  [[ -d "$RUNTIME_ROOT_ARGUMENT" ]] || fail "runtime root does not exist: $RUNTIME_ROOT_ARGUMENT"
  RUNTIME_ROOT="$(cd "$RUNTIME_ROOT_ARGUMENT" && pwd -P)"
else
  git_common_dir="$(
    git -C "$SOURCE_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null
  )" || fail "source root is not inside a Git Worktree: $SOURCE_ROOT"
  [[ -d "$git_common_dir" ]] || fail "Git common directory does not exist: $git_common_dir"
  RUNTIME_ROOT="$(cd "$(dirname "$git_common_dir")" && pwd -P)"
fi

RUNTIME_ENV_FILE="$RUNTIME_ROOT/.env"
RUNTIME_DATA_DIR="$RUNTIME_ROOT/data"
RUNTIME_LOG_DIR="$RUNTIME_ROOT/logs"

[[ -f "$RUNTIME_ENV_FILE" && ! -L "$RUNTIME_ENV_FILE" ]] \
  || fail "runtime .env must be a regular, non-symlink file: $RUNTIME_ENV_FILE"
[[ -d "$RUNTIME_DATA_DIR" && ! -L "$RUNTIME_DATA_DIR" ]] \
  || fail "runtime data must be a real, non-symlink directory: $RUNTIME_DATA_DIR"
if [[ -e "$RUNTIME_LOG_DIR" ]]; then
  [[ -d "$RUNTIME_LOG_DIR" && ! -L "$RUNTIME_LOG_DIR" ]] \
    || fail "runtime logs must be a real, non-symlink directory: $RUNTIME_LOG_DIR"
fi

cd "$SOURCE_ROOT"

read_setting() {
  local name="$1"
  local default_value="$2"
  local value="${!name-}"

  if [[ -z "$value" ]]; then
    value="$(
      awk -F= -v key="$name" \
        '$1 == key {print substr($0, index($0, "=") + 1)}' \
        "$RUNTIME_ENV_FILE" | tail -n 1
    )"
    value="${value%$'\r'}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "${value:-$default_value}"
}

BUILD_FLAGS=("--pull")

[[ -f "$SOURCE_ROOT/docker-compose.light.yml" ]] \
  || fail "required light Compose file is missing: $SOURCE_ROOT/docker-compose.light.yml"
COMPOSE=(
  docker compose
  --project-name infohub-light
  --env-file "$RUNTIME_ENV_FILE"
  -f "$SOURCE_ROOT/docker-compose.light.yml"
)
LIGHT_SERVICES=("horizon-api" "horizon-worker")
LIGHT_MANUAL_SERVICE="horizon"
SERVICES=("${LIGHT_SERVICES[@]}")
MANUAL_SERVICE="$LIGHT_MANUAL_SERVICE"
API_CONTAINER="horizon-light-api"
WORKER_CONTAINER="horizon-light-worker"
PRUNE_PROJECT="infohub-light"
DEFAULT_WEB_PORT="8080"

revision="$(git -C "$SOURCE_ROOT" rev-parse --short=12 HEAD 2>/dev/null || printf unknown)"
if [[ -n "$(git -C "$SOURCE_ROOT" status --porcelain 2>/dev/null || true)" ]]; then
  revision="${revision}-dirty"
fi
source_version="$(
  awk -F'"' '/^version[[:space:]]*=[[:space:]]*"/ {print $2; exit}' \
    "$SOURCE_ROOT/pyproject.toml"
)"
[[ "$source_version" =~ ^[0-9A-Za-z][0-9A-Za-z.+-]*$ ]] \
  || fail "could not resolve a valid version from $SOURCE_ROOT/pyproject.toml"
export INTELISCOPE_RUNTIME_ROOT="$RUNTIME_ROOT"
export INTELISCOPE_VERSION="$source_version"
export INTELISCOPE_BUILD_REVISION="$revision"
export INTELISCOPE_BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export INTELISCOPE_IMAGE="inteliscope-service:local-${revision}"

if [[ "$(read_setting HORIZON_BUILD_NO_CACHE true)" == "true" ]]; then
  BUILD_FLAGS+=("--no-cache")
fi

web_port="$(read_setting HORIZON_WEB_PORT "$DEFAULT_WEB_PORT")"
[[ "$web_port" =~ ^[0-9]+$ ]] \
  && (( web_port >= 1 && web_port <= 65535 )) \
  || fail "HORIZON_WEB_PORT must be an integer from 1 to 65535"

echo "==> Resolved local runtime"
echo "    source root: $SOURCE_ROOT"
echo "    runtime root: $RUNTIME_ROOT"
echo "    version: $INTELISCOPE_VERSION"
echo "    revision: $INTELISCOPE_BUILD_REVISION"
echo "    image: $INTELISCOPE_IMAGE"
echo "    web port: $web_port"
echo "    services: ${SERVICES[*]}"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "==> Dry run complete; Docker was not called"
  exit 0
fi

mkdir -p "$RUNTIME_LOG_DIR"
LOCK_ROOT="${TMPDIR:-/tmp}"
[[ "$LOCK_ROOT" == /* && -d "$LOCK_ROOT" ]] \
  || fail "TMPDIR must resolve to an existing absolute directory"
LOCK_ROOT="$(cd "$LOCK_ROOT" && pwd -P)"
RUNTIME_LOCK_DIR="$LOCK_ROOT/inteliscope-infohub-light-${UID}.up-latest.lock"
if ! mkdir "$RUNTIME_LOCK_DIR" 2>/dev/null; then
  [[ -d "$RUNTIME_LOCK_DIR" && ! -L "$RUNTIME_LOCK_DIR" ]] \
    || fail "shared local rebuild lock is not a real directory: $RUNTIME_LOCK_DIR"
  [[ -f "$RUNTIME_LOCK_DIR/owner" && ! -L "$RUNTIME_LOCK_DIR/owner" ]] \
    || fail "shared local rebuild lock has no trustworthy owner: $RUNTIME_LOCK_DIR"
  lock_owner_pid="$(
    awk -F= '$1 == "pid" {print $2}' "$RUNTIME_LOCK_DIR/owner" 2>/dev/null \
      | head -n 1
  )"
  if [[ "$lock_owner_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$lock_owner_pid" 2>/dev/null; then
    stale_lock_dir="${RUNTIME_LOCK_DIR}.stale.$$"
    if mv "$RUNTIME_LOCK_DIR" "$stale_lock_dir" 2>/dev/null; then
      rm -f "$stale_lock_dir/owner"
      rmdir "$stale_lock_dir" 2>/dev/null \
        || fail "stale local rebuild lock contains unexpected files: $stale_lock_dir"
      mkdir "$RUNTIME_LOCK_DIR" 2>/dev/null \
        || fail "another local rebuild acquired the shared Docker project"
    else
      fail "another local rebuild acquired the shared Docker project"
    fi
  else
    fail "another local rebuild already owns the shared Docker project"
  fi
fi
release_runtime_lock() {
  rm -f "$RUNTIME_LOCK_DIR/owner"
  rmdir "$RUNTIME_LOCK_DIR" 2>/dev/null || true
}
trap release_runtime_lock EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 700 "$RUNTIME_LOCK_DIR"
printf 'pid=%s\nsource=%s\nruntime=%s\n' \
  "$$" "$SOURCE_ROOT" "$RUNTIME_ROOT" > "$RUNTIME_LOCK_DIR/owner"
chmod 600 "$RUNTIME_LOCK_DIR/owner"

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
docker compose version >/dev/null 2>&1 || fail "docker compose is unavailable"

echo "==> Building current workspace into Docker images"
echo "    ${COMPOSE[*]} build ${BUILD_FLAGS[*]} ${SERVICES[*]} $MANUAL_SERVICE"
"${COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${SERVICES[@]}" "$MANUAL_SERVICE"

echo "==> Recreating running services from freshly built images"
"${COMPOSE[@]}" up -d --no-build --force-recreate --remove-orphans "${SERVICES[@]}"

base_url="http://127.0.0.1:${web_port}"
live_url="http://127.0.0.1:${web_port}/api/health/live"
ready_url="http://127.0.0.1:${web_port}/api/health/ready"
echo "==> Waiting for API liveness and readiness"
for attempt in $(seq 1 90); do
  live_payload="$(curl -fsS --max-time 3 "$live_url" 2>/dev/null || true)"
  ready_payload="$(curl -sS --max-time 3 "$ready_url" 2>/dev/null || true)"
  if [[ "$ready_payload" == *'"migration_required"'* ]]; then
    if [[ "$live_payload" != *"\"revision\":\"$INTELISCOPE_BUILD_REVISION\""* ]]; then
      fail "migration response did not come from the target revision; refusing to stop services"
    fi
    if ! "${COMPOSE[@]}" stop "${SERVICES[@]}" >/dev/null 2>&1; then
      echo "Database migration is required, but API and Worker could not be stopped." >&2
      echo "Do not run a migration until both containers are confirmed stopped." >&2
      exit 1
    fi
    api_running="$(
      docker inspect --format '{{.State.Running}}' "$API_CONTAINER" 2>/dev/null || true
    )"
    worker_running="$(
      docker inspect --format '{{.State.Running}}' "$WORKER_CONTAINER" 2>/dev/null || true
    )"
    if [[ "$api_running" != "false" || "$worker_running" != "false" ]]; then
      echo "Database migration is required, but stopped-container verification failed." >&2
      echo "Do not run a migration until both containers report State.Running=false." >&2
      exit 1
    fi
    migration_script=""
    if [[ "$ready_payload" == *"Apify Discovery limits v16"* ]]; then
      migration_script="scripts/migrate_apify_discovery_limits_v16.py"
    elif [[ "$ready_payload" == *"Apify ActorOps v15"* ]]; then
      migration_script="scripts/migrate_apify_actor_ops_v15.py"
    elif [[ "$ready_payload" == *"Webhook providers v14"* ]]; then
      migration_script="scripts/migrate_webhook_providers_v14.py"
    elif [[ "$ready_payload" == *"Apify Actor routing v13"* ]]; then
      migration_script="scripts/migrate_apify_actor_routing_v13.py"
    elif [[ "$ready_payload" == *"content timeline v11"* ]]; then
      migration_script="scripts/migrate_content_timeline_v11.py"
    elif [[ "$ready_payload" == *"user content v4"* ]]; then
      migration_script="scripts/migrate_user_content_v4.py"
    elif [[ "$ready_payload" == *"user feed v2"* ]]; then
      migration_script="scripts/migrate_user_feed_v2.py"
    fi
    echo "Database migration is required; API and Worker are confirmed stopped." >&2
    if [[ -n "$migration_script" ]]; then
      migration_python="python3"
      if [[ -x "$RUNTIME_ROOT/.venv/bin/python" ]]; then
        migration_python="$RUNTIME_ROOT/.venv/bin/python"
      fi
      printf 'Review the backup impact, then run:\n    cd %q && %q %q --data-dir %q --backup-dir %q --apply\n' \
        "$SOURCE_ROOT" \
        "$migration_python" \
        "$migration_script" \
        "$RUNTIME_DATA_DIR" \
        "$RUNTIME_DATA_DIR/backups" >&2
    else
      echo "Inspect $ready_url for the required explicit migration action." >&2
    fi
    exit 1
  fi
  if [[
    "$live_payload" == *"\"revision\":\"$INTELISCOPE_BUILD_REVISION\""*
    && "$ready_payload" == *'"status":"ready"'*
    && "$ready_payload" == *'"worker_status":"ready"'*
  ]]; then
    break
  fi
  if [[ "$attempt" -eq 90 ]]; then
    echo "API failed release identity/readiness verification" >&2
    "${COMPOSE[@]}" logs --tail=200 "${SERVICES[@]}" >&2 || true
    exit 1
  fi
  sleep 2
done
echo "    live revision: $INTELISCOPE_BUILD_REVISION"
echo "    readiness: API and Worker ready"

echo "==> Waiting for container health"
for attempt in $(seq 1 90); do
  api_health="$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || true)"
  worker_health="$(docker inspect --format '{{.State.Health.Status}}' "$WORKER_CONTAINER" 2>/dev/null || true)"
  if [[ "$api_health" == "healthy" && "$worker_health" == "healthy" ]]; then
    break
  fi
  if [[ "$api_health" == "unhealthy" || "$worker_health" == "unhealthy" || "$attempt" -eq 90 ]]; then
    echo "API/Worker containers failed health verification" >&2
    "${COMPOSE[@]}" logs --tail=200 "${SERVICES[@]}" >&2 || true
    exit 1
  fi
  sleep 1
done
echo "    containers: API healthy, Worker healthy"

echo "==> Verifying the served frontend asset"
root_html="$(curl -fsS --max-time 5 "$base_url/" 2>/dev/null || true)"
asset_path="$(
  printf '%s' "$root_html" \
    | grep -oE '/assets/[^"[:space:]]+\.js' \
    | head -n 1 \
    || true
)"
[[ -n "$asset_path" ]] || fail "React frontend asset was not found in the served page"
curl -fsS --max-time 10 "$base_url$asset_path" >/dev/null \
  || fail "served frontend asset failed to load: $asset_path"
echo "    served frontend asset: ${asset_path##*/}"

if [[ "$(read_setting HORIZON_PRUNE_OLD_IMAGES true)" == "true" ]]; then
  echo "==> Removing old dangling images for this Compose project"
  docker image prune -f --filter "label=com.docker.compose.project=$PRUNE_PROJECT" >/dev/null || true
fi

if [[ "$(read_setting HORIZON_PRUNE_BUILD_CACHE true)" == "true" ]]; then
  prune_until="$(read_setting HORIZON_PRUNE_BUILD_CACHE_UNTIL 24h)"
  echo "==> Removing Docker build cache older than $prune_until"
  docker builder prune -f --filter "until=$prune_until" >/dev/null || true
fi

echo "==> Current service status"
"${COMPOSE[@]}" ps
final_live_payload="$(curl -fsS --max-time 3 "$live_url" 2>/dev/null || true)"
final_ready_payload="$(curl -sS --max-time 3 "$ready_url" 2>/dev/null || true)"
final_api_health="$(docker inspect --format '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || true)"
final_worker_health="$(docker inspect --format '{{.State.Health.Status}}' "$WORKER_CONTAINER" 2>/dev/null || true)"
[[ "$final_live_payload" == *"\"revision\":\"$INTELISCOPE_BUILD_REVISION\""* ]] \
  || fail "live revision changed before final completion verification"
[[
  "$final_ready_payload" == *'"status":"ready"'*
  && "$final_ready_payload" == *'"worker_status":"ready"'*
]] || fail "API/Worker readiness changed before final completion verification"
[[ "$final_api_health" == "healthy" && "$final_worker_health" == "healthy" ]] \
  || fail "container health changed before final completion verification"
echo "==> Local rebuild complete"
echo "    revision: $INTELISCOPE_BUILD_REVISION"
echo "    API and Worker: healthy"
echo "    frontend: served from $base_url/"
