#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${INTELISCOPE_DEPLOY_HOST:-vps-tokyo}"
REMOTE_BASE="${INTELISCOPE_DEPLOY_BASE:-/opt/inteliscope}"
PUBLIC_URL="${INTELISCOPE_PUBLIC_URL:-https://rb.jiefs.top}"
PLATFORM="${INTELISCOPE_DEPLOY_PLATFORM:-linux/amd64}"
CI_TIMEOUT_SECONDS="${INTELISCOPE_RELEASE_CI_TIMEOUT_SECONDS:-1800}"
PYTHON_BIN="${INTELISCOPE_RELEASE_PYTHON:-$ROOT_DIR/.venv/bin/python}"
RELEASE_TMP_DIR=""
REMOTE_RELEASE_STAGE=""
LOCAL_RELEASE_IMAGE=""
TAG_CREATED=false
TAG_PUSHED=false

usage() {
  echo "Usage: $0 release <vX.Y.Z> | preflight <vX.Y.Z> | rollback [release-id] | status"
}

fail() {
  echo "release error: $*" >&2
  exit 1
}

require_frozen_release_source() {
  local expected_revision="$1"
  [[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$expected_revision" ]] \
    || fail "release source revision changed while artifacts were being prepared"
  [[ -z "$(git -C "$ROOT_DIR" status --porcelain --untracked-files=all)" ]] \
    || fail "release source became dirty while artifacts were being prepared"
}

cleanup() {
  [[ "${BASH_SUBSHELL:-0}" -eq 0 ]] || return
  if [[ -n "$RELEASE_TMP_DIR" && -d "$RELEASE_TMP_DIR" ]]; then
    rm -rf "$RELEASE_TMP_DIR"
  fi
  if [[ "$REMOTE_RELEASE_STAGE" =~ ^/tmp/inteliscope-release-[A-Za-z0-9._-]+$ ]]; then
    ssh -o ConnectTimeout=10 "$REMOTE_HOST" bash -s -- "$REMOTE_RELEASE_STAGE" <<'REMOTE' >/dev/null 2>&1 || true
set -euo pipefail
stage="$1"
[[ "$stage" =~ ^/tmp/inteliscope-release-[A-Za-z0-9._-]+$ ]]
rm -rf -- "$stage"
REMOTE
  fi
  if [[ -n "$LOCAL_RELEASE_IMAGE" ]]; then
    docker image rm "$LOCAL_RELEASE_IMAGE" >/dev/null 2>&1 || true
  fi
  if [[ "$TAG_CREATED" == true && "$TAG_PUSHED" == false ]]; then
    git -C "$ROOT_DIR" tag -d "$RELEASE_TAG" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

require_commands() {
  local command
  for command in git docker rsync ssh gh gzip shasum; do
    command -v "$command" >/dev/null 2>&1 || fail "required command is unavailable: $command"
  done
  [[ -x "$PYTHON_BIN" ]] || fail "project Python is unavailable: $PYTHON_BIN"
  docker buildx version >/dev/null 2>&1 || fail "docker buildx is unavailable"
}

project_version() {
  "$PYTHON_BIN" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
}

require_release_identity() {
  local expected_tag remote_head
  cd "$ROOT_DIR"
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] \
    || fail "working tree is dirty; commit the authorized release first"
  [[ "$(git branch --show-current)" == main ]] \
    || fail "normal VPS release must run from main"
  git fetch --prune origin main --tags
  remote_head="$(git rev-parse origin/main)"
  [[ "$(git rev-parse HEAD)" == "$remote_head" ]] \
    || fail "local main must exactly match origin/main"
  expected_tag="v$(project_version)"
  [[ "$RELEASE_TAG" == "$expected_tag" ]] \
    || fail "tag $RELEASE_TAG does not match pyproject version $expected_tag"
  [[ -z "$(git tag --list "$RELEASE_TAG")" ]] \
    || fail "local tag already exists: $RELEASE_TAG"
  if git ls-remote --exit-code --tags origin "refs/tags/$RELEASE_TAG" >/dev/null 2>&1; then
    fail "remote tag already exists: $RELEASE_TAG"
  fi
}

release_base_ref() {
  git -C "$ROOT_DIR" describe --tags --abbrev=0 --match 'v*' HEAD^ 2>/dev/null \
    || git -C "$ROOT_DIR" rev-parse HEAD^
}

reject_implicit_migrations() {
  local base_ref="$1" migration_files schema_delta
  migration_files="$(
    git -C "$ROOT_DIR" diff --name-only "$base_ref"...HEAD -- 'scripts/migrate_*.py'
  )"
  schema_delta="$(
    git -C "$ROOT_DIR" diff -U0 "$base_ref"...HEAD -- src/storage/service_store.py \
      | grep -E '^[+-].*(CREATE TABLE|ALTER TABLE|DROP TABLE|schema_migrations|PRAGMA user_version)' \
      || true
  )"
  [[ -z "$migration_files" && -z "$schema_delta" ]] || fail \
    "release contains a database migration; use the explicit migration workflow before normal cutover"
}

remote_capacity_preflight() {
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" <<'REMOTE'
set -euo pipefail
base="$1"
probe="$base"
[[ -d "$probe" ]] || probe="$(dirname "$base")"
read -r available_kib used_percent < <(
  df -Pk "$probe" | awk 'NR == 2 {gsub(/%/, "", $5); print $4, $5}'
)
[[ "$available_kib" =~ ^[0-9]+$ && "$used_percent" =~ ^[0-9]+$ ]] || {
  echo "could not determine VPS disk capacity" >&2
  exit 1
}
if (( used_percent > 85 || available_kib < 8388608 )); then
  echo "VPS capacity preflight failed: used=${used_percent}% available_kib=${available_kib}" >&2
  echo "Read-only cleanup inventory (nothing was deleted):" >&2
  df -h "$probe" >&2 || true
  docker system df >&2 || true
  du -x -h -d 1 "$base/releases" "$base/backups" "$base/logs" 2>/dev/null \
    | sort -h >&2 || true
  find /tmp -maxdepth 1 -type d -name 'inteliscope-release-*' \
    -exec du -sh -- {} + 2>/dev/null | sort -h >&2 || true
  exit 1
fi
echo "VPS capacity ready: used=${used_percent}% available_kib=${available_kib}"
REMOTE
}

run_quick_preflight() {
  local base_ref
  require_commands
  require_release_identity
  base_ref="$(release_base_ref)"
  reject_implicit_migrations "$base_ref"
  remote_capacity_preflight
  cd "$ROOT_DIR"
  "$PYTHON_BIN" scripts/test_gate.py preflight \
    --base "$base_ref" --head HEAD
  echo "Preflight passed for $RELEASE_TAG against $base_ref"
}

wait_for_workflow_success() {
  local workflow="$1" revision="$2" head_branch="$3"
  local started now runs state url
  started="$(date +%s)"
  while true; do
    runs="$(
      gh run list --workflow "$workflow" --commit "$revision" --limit 20 \
        --json status,conclusion,event,headBranch,url
    )"
    read -r state url <<<"$(
      "$PYTHON_BIN" -c '
import json, sys
branch = sys.argv[1]
runs = [r for r in json.load(sys.stdin) if r.get("event") == "push" and r.get("headBranch") == branch]
successful = next((r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"), None)
pending = next((r for r in runs if r.get("status") != "completed"), None)
failed = next((r for r in runs if r.get("status") == "completed" and r.get("conclusion") != "success"), None)
selected = successful or pending or failed
if successful:
    print("success", successful.get("url", ""))
elif pending:
    print("pending", pending.get("url", ""))
elif failed:
    print("failure", failed.get("url", ""))
else:
    print("missing", "")
' "$head_branch" <<<"$runs"
    )"
    case "$state" in
      success)
        echo "$workflow passed for $revision: $url"
        return 0
        ;;
      failure)
        fail "$workflow failed for $revision: $url"
        ;;
    esac
    now="$(date +%s)"
    (( now - started < CI_TIMEOUT_SECONDS )) \
      || fail "timed out waiting for $workflow on $revision"
    sleep 15
  done
}

build_package_and_upload() {
  local revision_short="$1" revision_full="$2" version="$3" built_at="$4" release_id="$5"
  local image="$6" archive image_archive expected_arch actual_arch image_revision image_source_digest source_digest
  local source_sha image_sha remote_stage source_pid image_pid source_status image_status
  archive="$RELEASE_TMP_DIR/source.tar.gz"
  image_archive="$RELEASE_TMP_DIR/image.tar.gz"
  expected_arch="${PLATFORM#linux/}"
  source_digest="git:$revision_full"
  remote_stage="/tmp/inteliscope-release-$release_id"

  transfer_with_retry() {
    local source="$1" destination="$2" attempt
    for attempt in 1 2 3; do
      if rsync --partial -az "$source" "$destination"; then
        return 0
      fi
      [[ "$attempt" -lt 3 ]] || return 1
      sleep 5
    done
  }

  require_frozen_release_source "$revision_full"
  docker buildx build \
    --platform "$PLATFORM" \
    --load \
    --build-arg "INTELISCOPE_VERSION=$version" \
    --build-arg "INTELISCOPE_BUILD_REVISION=$revision_short" \
    --build-arg "INTELISCOPE_SOURCE_DIGEST=$source_digest" \
    --build-arg "INTELISCOPE_BUILT_AT=$built_at" \
    --tag "$image" \
    "$ROOT_DIR"
  require_frozen_release_source "$revision_full"
  actual_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
  image_revision="$(
    docker image inspect "$image" \
      --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
  )"
  image_source_digest="$(
    docker image inspect "$image" \
      --format '{{index .Config.Labels "io.inteliscope.source.digest"}}'
  )"
  [[ "$actual_arch" == "$expected_arch" ]] \
    || fail "image architecture mismatch: expected=$expected_arch actual=$actual_arch"
  [[ "$image_revision" == "$revision_short" ]] \
    || fail "image revision mismatch: expected=$revision_short actual=$image_revision"
  [[ "$image_source_digest" == "$source_digest" ]] \
    || fail "image source mismatch: expected=$source_digest actual=$image_source_digest"
  docker run --rm --network none \
    --entrypoint /app/.venv/bin/horizon-api "$image" --help >/dev/null
  docker run --rm --network none \
    --entrypoint /app/.venv/bin/horizon-worker "$image" --help >/dev/null

  git -C "$ROOT_DIR" archive --format=tar.gz --output="$archive" "$revision_full"
  docker save "$image" | gzip -1 >"$image_archive"
  source_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
  image_sha="$(shasum -a 256 "$image_archive" | awk '{print $1}')"
  ssh "$REMOTE_HOST" mkdir -p "$remote_stage"

  transfer_with_retry "$archive" "$REMOTE_HOST:$remote_stage/source.tar.gz" &
  source_pid=$!
  transfer_with_retry "$image_archive" "$REMOTE_HOST:$remote_stage/image.tar.gz" &
  image_pid=$!
  set +e
  wait "$source_pid"; source_status=$?
  wait "$image_pid"; image_status=$?
  set -e
  [[ "$source_status" -eq 0 && "$image_status" -eq 0 ]] \
    || fail "resumable release upload failed"

  ssh "$REMOTE_HOST" bash -s -- \
    "$remote_stage" "$source_sha" "$image_sha" <<'REMOTE'
set -euo pipefail
remote_stage="$1"
expected_source_sha="$2"
expected_image_sha="$3"
[[ "$(sha256sum "$remote_stage/source.tar.gz" | awk '{print $1}')" == "$expected_source_sha" ]]
[[ "$(sha256sum "$remote_stage/image.tar.gz" | awk '{print $1}')" == "$expected_image_sha" ]]
REMOTE
}

deploy_remote_release() {
  local release_id="$1" image="$2" version="$3" revision="$4" built_at="$5" source_digest="$6"
  local remote_stage="/tmp/inteliscope-release-$release_id"
  ssh "$REMOTE_HOST" bash -s -- \
    "$REMOTE_BASE" "$release_id" "$image" "$version" "$revision" "$built_at" "$source_digest" \
    "$remote_stage" "$PUBLIC_URL" <<'REMOTE'
set -euo pipefail
base="$1"
release_id="$2"
image="$3"
version="$4"
revision="$5"
built_at="$6"
source_digest="$7"
remote_stage="$8"
public_url="$9"
release_dir="$base/releases/$release_id"
backup_dir="$base/backups/$release_id"
previous_release=""

[[ -f "$base/.env" ]] || { echo "missing canonical runtime .env" >&2; exit 1; }
[[ -f "$base/data/service.db" ]] || { echo "missing canonical service.db" >&2; exit 1; }
[[ -L "$base/current" ]] || { echo "normal upgrade requires an existing current release" >&2; exit 1; }
previous_release="$(readlink -f "$base/current")"
[[ -d "$previous_release" ]] || { echo "previous release is unavailable: $previous_release" >&2; exit 1; }
[[ ! -e "$release_dir" ]] || { echo "release already exists: $release_dir" >&2; exit 1; }
if docker ps --format '{{.Names}}' | grep -Eq '^horizon(-light)?-scheduler$'; then
  echo "legacy scheduler must remain stopped during Service releases" >&2
  exit 1
fi

validate_database() {
  python3 - "$base/data/service.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
try:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    active_jobs = connection.execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued', 'running')"
    ).fetchone()[0]
finally:
    connection.close()
if integrity != "ok" or foreign_keys or active_jobs:
    raise SystemExit(
        f"database preflight failed: integrity={integrity!r} "
        f"foreign_keys={len(foreign_keys)} active_jobs={active_jobs}"
    )
PY
}

set_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$base/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$base/.env"
  else
    printf '%s=%s\n' "$key" "$value" >>"$base/.env"
  fi
}

wait_runtime() {
  local target_release="$1" target_public_url="$2"
  local target_version target_revision target_source_digest public_args=() source_args=()
  target_version="$(grep '^INTELISCOPE_VERSION=' "$target_release/release-metadata.env" | cut -d= -f2-)"
  target_revision="$(grep '^INTELISCOPE_BUILD_REVISION=' "$target_release/release-metadata.env" | cut -d= -f2-)"
  target_source_digest="$(grep '^INTELISCOPE_SOURCE_DIGEST=' "$target_release/release-metadata.env" | cut -d= -f2- || true)"
  [[ -n "$target_version" && -n "$target_revision" ]]
  if [[ -n "$target_public_url" ]]; then
    public_args=(--public-url "$target_public_url")
  fi
  if [[ -n "$target_source_digest" ]]; then
    source_args=(--expected-source-digest "$target_source_digest")
  fi
  python3 "$release_dir/scripts/runtime_health.py" \
    --base-url http://127.0.0.1:8080 \
    --expected-version "$target_version" \
    --expected-revision "$target_revision" \
    "${source_args[@]}" \
    --api-container horizon-light-api \
    --worker-container horizon-light-worker \
    "${public_args[@]}" \
    --timeout 180 \
    --interval 2
}

rollback_cutover() {
  local status=$? migration_backup=""
  trap - ERR INT TERM
  echo "cutover failed; restoring $previous_release" >&2
  install -m 600 "$backup_dir/env.before" "$base/.env" || {
    echo "rollback failed; canonical environment could not be restored" >&2
    exit 1
  }
  migration_backup="$(
    grep '^INTELISCOPE_PRE_MIGRATION_BACKUP=' "$backup_dir/env.before" \
      | tail -n 1 | cut -d= -f2- || true
  )"
  docker stop --time 20 horizon-light-worker horizon-light-api >/dev/null 2>&1 || true
  if [[ -n "$migration_backup" ]]; then
    [[ "$migration_backup" == "$base/data/backups/"* \
      && -f "$migration_backup" && ! -L "$migration_backup" \
      && "$(stat -c '%a' "$migration_backup")" == "600" ]] || {
      echo "rollback database backup is invalid: $migration_backup" >&2
      exit 1
    }
    install -m 600 "$migration_backup" "$base/data/service.db"
    validate_database
  fi
  cd "$previous_release"
  if ! docker compose -f docker-compose.light.yml up -d --no-build --force-recreate \
    horizon-api horizon-worker \
    || ! wait_runtime "$previous_release" "$public_url"; then
    docker compose -f docker-compose.light.yml logs horizon-api horizon-worker || true
    echo "rollback failed; previous runtime is not healthy" >&2
    exit 1
  fi
  ln -sfn "$previous_release" "$base/current" || exit 1
  echo "rollback restored healthy runtime: $previous_release" >&2
  exit "$status"
}

validate_database
mkdir -p "$base/releases" "$base/backups"
install -d -m 700 "$backup_dir"
install -m 600 "$base/.env" "$backup_dir/env.before"
if [[ ! -f "$previous_release/release-metadata.env" ]]; then
  previous_metadata_tmp="$backup_dir/previous-release-metadata.env"
  : >"$previous_metadata_tmp"
  for metadata_key in INTELISCOPE_IMAGE INTELISCOPE_VERSION INTELISCOPE_BUILD_REVISION INTELISCOPE_BUILT_AT; do
    metadata_value="$(grep "^${metadata_key}=" "$backup_dir/env.before" | tail -n 1 | cut -d= -f2-)"
    [[ -n "$metadata_value" ]] || {
      echo "previous release metadata is incomplete: $metadata_key" >&2
      exit 1
    }
    printf '%s=%s\n' "$metadata_key" "$metadata_value" >>"$previous_metadata_tmp"
  done
  previous_source_digest="$(grep '^INTELISCOPE_SOURCE_DIGEST=' "$backup_dir/env.before" | tail -n 1 | cut -d= -f2- || true)"
  [[ -z "$previous_source_digest" ]] \
    || printf 'INTELISCOPE_SOURCE_DIGEST=%s\n' "$previous_source_digest" >>"$previous_metadata_tmp"
  install -m 600 "$previous_metadata_tmp" "$previous_release/release-metadata.env"
fi
python3 - "$base/data/service.db" "$backup_dir/service.db" <<'PY'
import os
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1], timeout=30)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
os.chmod(sys.argv[2], 0o600)
PY

mkdir "$release_dir"
tar -xzf "$remote_stage/source.tar.gz" -C "$release_dir" \
  --exclude='data' --exclude='data/*' \
  --exclude='logs' --exclude='logs/*' \
  --exclude='.env'
ln -s "$base/data" "$release_dir/data"
ln -s "$base/logs" "$release_dir/logs"
ln -s "$base/.env" "$release_dir/.env"
printf '%s\n' "$previous_release" >"$release_dir/previous_release"
printf 'INTELISCOPE_IMAGE=%s\nINTELISCOPE_VERSION=%s\nINTELISCOPE_BUILD_REVISION=%s\nINTELISCOPE_SOURCE_DIGEST=%s\nINTELISCOPE_BUILT_AT=%s\n' \
  "$image" "$version" "$revision" "$source_digest" "$built_at" >"$release_dir/release-metadata.env"
chmod 600 "$release_dir/release-metadata.env"

docker load -i "$remote_stage/image.tar.gz"
loaded_arch="$(docker image inspect "$image" --format '{{.Architecture}}')"
loaded_revision="$(
  docker image inspect "$image" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
)"
loaded_source_digest="$(
  docker image inspect "$image" \
    --format '{{index .Config.Labels "io.inteliscope.source.digest"}}'
)"
[[ "$loaded_arch" == amd64 ]]
[[ "$loaded_revision" == "$revision" ]]
[[ "$loaded_source_digest" == "$source_digest" ]]

trap rollback_cutover ERR INT TERM
docker stop --time 20 horizon-light-worker >/dev/null
validate_database
set_env INTELISCOPE_IMAGE "$image"
set_env INTELISCOPE_VERSION "$version"
set_env INTELISCOPE_BUILD_REVISION "$revision"
set_env INTELISCOPE_SOURCE_DIGEST "$source_digest"
set_env INTELISCOPE_BUILT_AT "$built_at"
chmod 600 "$base/.env"
cd "$release_dir"
docker compose -f docker-compose.light.yml up -d --no-build --force-recreate \
  horizon-api horizon-worker
wait_runtime "$release_dir" "$public_url"
# The full integrity/FK/active-job check ran while Worker was stopped above.
# Runtime health is the authoritative post-start check; do not race live jobs.
ln -sfn "$release_dir" "$base/current"
rm -rf "$remote_stage"
trap - ERR INT TERM
echo "deployed $release_id revision=$revision"
REMOTE
}

release() {
  local version revision_full revision_short built_at release_id image ci_pid package_pid
  local ci_status package_status
  run_quick_preflight
  version="$(project_version)"
  revision_full="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  revision_short="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)"
  built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  release_id="${RELEASE_TAG#v}-$(date -u +%Y%m%dT%H%M%SZ)-$revision_short"
  image="inteliscope-service:$release_id"
  LOCAL_RELEASE_IMAGE="$image"
  RELEASE_TMP_DIR="$(mktemp -d -t inteliscope-release.XXXXXX)"
  REMOTE_RELEASE_STAGE="/tmp/inteliscope-release-$release_id"

  wait_for_workflow_success test-gate.yml "$revision_full" main &
  ci_pid=$!
  build_package_and_upload \
    "$revision_short" "$revision_full" "$version" "$built_at" "$release_id" "$image" &
  package_pid=$!
  set +e
  wait "$ci_pid"; ci_status=$?
  wait "$package_pid"; package_status=$?
  set -e
  [[ "$ci_status" -eq 0 && "$package_status" -eq 0 ]] \
    || fail "main CI or release artifact preparation failed"
  require_frozen_release_source "$revision_full"

  git -C "$ROOT_DIR" tag -a "$RELEASE_TAG" -m "Release $RELEASE_TAG"
  TAG_CREATED=true
  git -C "$ROOT_DIR" push origin "refs/tags/$RELEASE_TAG"
  TAG_PUSHED=true
  wait_for_workflow_success release-tag.yml "$revision_full" "$RELEASE_TAG"
  deploy_remote_release "$release_id" "$image" "$version" "$revision_short" "$built_at" "git:$revision_full"
  REMOTE_RELEASE_STAGE=""
  echo "Release complete: $RELEASE_TAG ($release_id)"
}

rollback_release() {
  local requested_release="${1:-}"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" "$requested_release" "$PUBLIC_URL" <<'REMOTE'
set -euo pipefail
base="$1"
requested_release="$2"
public_url="$3"
current_release="$(readlink -f "$base/current")"
if [[ -z "$requested_release" ]]; then
  requested_release="$(basename "$(<"$current_release/previous_release")")"
fi
target="$base/releases/$requested_release"
[[ -d "$target" ]] || { echo "rollback target not found: $target" >&2; exit 1; }
[[ -f "$target/release-metadata.env" ]] || { echo "rollback metadata missing" >&2; exit 1; }

set_env() {
  key="$1"
  value="$2"
  if grep -q "^${key}=" "$base/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$base/.env"
  else
    printf '%s=%s\n' "$key" "$value" >>"$base/.env"
  fi
}
for key in INTELISCOPE_IMAGE INTELISCOPE_VERSION INTELISCOPE_BUILD_REVISION INTELISCOPE_BUILT_AT; do
  value="$(grep "^${key}=" "$target/release-metadata.env" | cut -d= -f2-)"
  [[ -n "$value" ]]
  set_env "$key" "$value"
done
source_digest="$(grep '^INTELISCOPE_SOURCE_DIGEST=' "$target/release-metadata.env" | cut -d= -f2- || true)"
if [[ -n "$source_digest" ]]; then
  set_env INTELISCOPE_SOURCE_DIGEST "$source_digest"
else
  sed -i '/^INTELISCOPE_SOURCE_DIGEST=/d' "$base/.env"
fi
migration_backup="$(
  grep '^INTELISCOPE_PRE_MIGRATION_BACKUP=' "$base/.env" \
    | tail -n 1 | cut -d= -f2- || true
)"
docker stop --time 20 horizon-light-worker horizon-light-api >/dev/null 2>&1 || true
if [[ -n "$migration_backup" ]]; then
  [[ "$migration_backup" == "$base/data/backups/"* \
    && -f "$migration_backup" && ! -L "$migration_backup" \
    && "$(stat -c '%a' "$migration_backup")" == "600" ]] \
    || { echo "rollback database backup is invalid" >&2; exit 1; }
  install -m 600 "$migration_backup" "$base/data/service.db"
  python3 - "$base/data/service.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not connection.execute("PRAGMA foreign_key_check").fetchall()
finally:
    connection.close()
PY
fi
cd "$target"
docker compose -f docker-compose.light.yml up -d --no-build --force-recreate \
  horizon-api horizon-worker
health_script="$current_release/scripts/runtime_health.py"
[[ -f "$health_script" ]] || { echo "shared runtime health checker is unavailable" >&2; exit 1; }
revision="$(grep '^INTELISCOPE_BUILD_REVISION=' "$target/release-metadata.env" | cut -d= -f2-)"
version="$(grep '^INTELISCOPE_VERSION=' "$target/release-metadata.env" | cut -d= -f2-)"
public_args=()
source_args=()
[[ -n "$public_url" ]] && public_args=(--public-url "$public_url")
[[ -n "$source_digest" ]] && source_args=(--expected-source-digest "$source_digest")
python3 "$health_script" \
  --base-url http://127.0.0.1:8080 \
  --expected-version "$version" \
  --expected-revision "$revision" \
  "${source_args[@]}" \
  --api-container horizon-light-api \
  --worker-container horizon-light-worker \
  "${public_args[@]}" \
  --timeout 180 \
  --interval 2
ln -sfn "$target" "$base/current"
echo "rolled back to $requested_release"
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
  release)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    RELEASE_TAG="$2"
    release
    ;;
  preflight)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    RELEASE_TAG="$2"
    run_quick_preflight
    ;;
  rollback)
    [[ $# -le 2 ]] || { usage; exit 2; }
    rollback_release "${2:-}"
    ;;
  status)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    show_status
    ;;
  *)
    usage
    exit 2
    ;;
esac
