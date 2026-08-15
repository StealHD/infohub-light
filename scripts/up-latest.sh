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
SERVICES=("${LIGHT_SERVICES[@]}")
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
echo "    ${COMPOSE[*]} build ${BUILD_FLAGS[*]} ${SERVICES[*]}"
"${COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${SERVICES[@]}"

echo "==> Recreating running services from freshly built images"
"${COMPOSE[@]}" up -d --no-build --force-recreate --remove-orphans "${SERVICES[@]}"

base_url="http://127.0.0.1:${web_port}"
live_url="http://127.0.0.1:${web_port}/api/health/live"
ready_url="http://127.0.0.1:${web_port}/api/health/ready"
echo "==> Waiting for target runtime health"
health_python="${INTELISCOPE_HEALTH_PYTHON:-python3}"
if [[ -x "$SOURCE_ROOT/.venv/bin/python" ]]; then
  health_python="$SOURCE_ROOT/.venv/bin/python"
fi
set +e
health_output="$(
  "$health_python" "$SOURCE_ROOT/scripts/runtime_health.py" \
    --base-url "$base_url" \
    --expected-version "$INTELISCOPE_VERSION" \
    --expected-revision "$INTELISCOPE_BUILD_REVISION" \
    --api-container "$API_CONTAINER" \
    --worker-container "$WORKER_CONTAINER" \
    --timeout "${INTELISCOPE_HEALTH_TIMEOUT_SECONDS:-180}" \
    --interval "${INTELISCOPE_HEALTH_INTERVAL_SECONDS:-2}" 2>&1
)"
health_status=$?
set -e
if [[ "$health_status" -eq 3 ]]; then
  live_payload="$(curl -fsS --max-time 3 "$live_url" 2>/dev/null || true)"
  ready_payload="$(curl -sS --max-time 3 "$ready_url" 2>/dev/null || true)"
  [[ "$live_payload" == *"\"revision\":\"$INTELISCOPE_BUILD_REVISION\""* ]] \
    || fail "migration response did not come from the target revision; refusing to stop services"
  if ! "${COMPOSE[@]}" stop "${SERVICES[@]}" >/dev/null 2>&1; then
    fail "database migration is required, but API and Worker could not be stopped"
  fi
  api_running="$(docker inspect --format '{{.State.Running}}' "$API_CONTAINER" 2>/dev/null || true)"
  worker_running="$(docker inspect --format '{{.State.Running}}' "$WORKER_CONTAINER" 2>/dev/null || true)"
  [[ "$api_running" == "false" && "$worker_running" == "false" ]] \
    || fail "database migration is required, but stopped-container verification failed"
  migration_script=""
  case "$ready_payload" in
    *"Apify Actor pool management v22"*) migration_script="scripts/migrate_apify_actor_pool_management_v22.py" ;;
    *"Apify Actor Canary batch"*) migration_script="scripts/migrate_apify_actor_canary_batches_v17.py" ;;
    *"Apify Discovery limits v16"*) migration_script="scripts/migrate_apify_discovery_limits_v16.py" ;;
    *"Apify ActorOps v15"*) migration_script="scripts/migrate_apify_actor_ops_v15.py" ;;
    *"notification targets v16"*) migration_script="scripts/migrate_notification_targets_v16.py" ;;
    *"notification channels v15"*) migration_script="scripts/migrate_notification_channels_v15.py" ;;
    *"Webhook providers v14"*) migration_script="scripts/migrate_webhook_providers_v14.py" ;;
    *"Apify Actor routing v13"*) migration_script="scripts/migrate_apify_actor_routing_v13.py" ;;
    *"content timeline v11"*) migration_script="scripts/migrate_content_timeline_v11.py" ;;
    *"user content v4"*) migration_script="scripts/migrate_user_content_v4.py" ;;
    *"user feed v2"*) migration_script="scripts/migrate_user_feed_v2.py" ;;
  esac
  echo "Database migration is required; API and Worker are confirmed stopped." >&2
  if [[ -n "$migration_script" ]]; then
    migration_python="python3"
    [[ -x "$RUNTIME_ROOT/.venv/bin/python" ]] && migration_python="$RUNTIME_ROOT/.venv/bin/python"
    printf 'Review the backup impact, then run:\n    cd %q && %q %q --data-dir %q --backup-dir %q --apply\n' \
      "$SOURCE_ROOT" "$migration_python" "$migration_script" \
      "$RUNTIME_DATA_DIR" "$RUNTIME_DATA_DIR/backups" >&2
  else
    echo "Inspect $ready_url for the required explicit migration action." >&2
  fi
  exit 1
elif [[ "$health_status" -ne 0 ]]; then
  echo "$health_output" >&2
  "${COMPOSE[@]}" logs --tail=200 "${SERVICES[@]}" >&2 || true
  fail "API/Worker runtime health verification failed"
fi
echo "    $health_output"
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

if [[ "$(read_setting HORIZON_PRUNE_OLD_LOCAL_BUILDS true)" == "true" ]]; then
  stale_local_images=()
  while IFS= read -r image_ref; do
    [[ -n "$image_ref" && "$image_ref" != "$INTELISCOPE_IMAGE" ]] || continue
    stale_local_images+=("$image_ref")
  done < <(
    docker image ls \
      --filter "reference=inteliscope-service:local-*" \
      --format '{{.Repository}}:{{.Tag}}'
  )

  if [[ "${#stale_local_images[@]}" -gt 0 ]]; then
    echo "==> Removing ${#stale_local_images[@]} old local project image tag(s)"
    # Do not force removal: Docker retains any image still referenced by a container.
    docker image rm "${stale_local_images[@]}" >/dev/null || true
  else
    echo "==> No old local project images to remove"
  fi
fi

echo "==> Local rebuild complete"
echo "    revision: $INTELISCOPE_BUILD_REVISION"
echo "    API and Worker: healthy"
echo "    frontend: served from $base_url/"
