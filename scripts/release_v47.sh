#!/usr/bin/env bash
# Explicit global 47 release helpers, sourced by release_vps.sh after shared helpers.

verify_notification_destinations_v47_receipt() {
  local receipt_path="$1" revision="$2"
  [[ "$receipt_path" == "$REMOTE_BASE/data/backups/"*.json ]] \
    || fail "migration receipt must be an absolute JSON file under $REMOTE_BASE/data/backups"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" "$receipt_path" "$revision" <<'REMOTE'
set -euo pipefail
base="$1"
receipt_path="$2"
revision="$3"
python3 - "$base" "$receipt_path" "$revision" <<'PY'
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

base = Path(sys.argv[1])
receipt_path = Path(sys.argv[2])
revision = sys.argv[3]
backup_dir = base / 'data' / 'backups'
database = base / 'data' / 'service.db'

def private_regular(path: Path) -> None:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError(f'unsafe private file: {path}')

if receipt_path.parent != backup_dir or not receipt_path.name.endswith('.json'):
    raise ValueError('receipt path escapes the managed backup directory')
private_regular(receipt_path)
with receipt_path.open(encoding='utf-8') as handle:
    receipt = json.load(handle)
expected = {
    'schema': 'notification_destinations_v47_release_receipt_v1',
    'migration': 'notification_destinations_v47',
    'release_revision': revision,
    'marker': {
        'version': 47,
        'name': 'notification_destinations',
        'checksum': 'notification-destinations-v1',
    },
}
if any(receipt.get(key) != value for key, value in expected.items()):
    raise ValueError('receipt is not bound to this release and v47 marker')
backup = receipt.get('backup')
if not isinstance(backup, dict) or backup.get('mode') != '0o600':
    raise ValueError('receipt backup metadata is invalid')
backup_path = Path(str(backup.get('path', '')))
if backup_path.parent != backup_dir:
    raise ValueError('receipt backup escapes the managed backup directory')
private_regular(backup_path)
connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=30)
try:
    # The complete integrity/FK scan ran with services stopped during migration.
    # Repeating it against a live DELETE-journal database blocks Worker writes.
    marker = connection.execute(
        'SELECT name, checksum FROM schema_migrations WHERE version=47'
    ).fetchone()
    if marker != ('notification_destinations', 'notification-destinations-v1'):
        raise ValueError('production database does not have the v47 marker')
    expected_tables = {
        'notification_target_topics': {'target_id', 'message_thread_id'},
        'openclaw_notification_services': {
            'id', 'workspace_id', 'name', 'name_key', 'channel_id', 'account_id',
            'destination_env_name', 'destination_digest', 'message_thread_id', 'enabled',
            'config_generation', 'activation_generation', 'last_test_status',
            'last_test_generation', 'last_tested_at', 'archived_at', 'created_at', 'updated_at',
        },
        'information_preview_notifications': {
            'preview_id', 'target_id', 'target_generation', 'target_activation', 'status',
            'delivery_started_at', 'ready_at', 'receipt_json', 'reason', 'created_at', 'updated_at',
        },
    }
    for table, columns in expected_tables.items():
        actual = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
        if actual != columns:
            raise ValueError(f'production v47 table shape is invalid: {table}')
finally:
    connection.close()
print(backup_path)
PY
REMOTE
}

migrate_notification_destinations_v47() {
  local base_ref migration_files schema_delta revision revision_short source_archive source_sha
  local receipt_path verified_backup
  require_commands
  require_release_identity
  base_ref="$(release_base_ref)"
  migration_files="$(
    git -C "$ROOT_DIR" diff --name-only "$base_ref"...HEAD -- 'scripts/migrate_*.py'
  )"
  schema_delta="$(
    git -C "$ROOT_DIR" diff -U0 "$base_ref"...HEAD -- src/storage/service_store.py \
      | grep -E '^[+-].*(CREATE TABLE|ALTER TABLE|DROP TABLE|schema_migrations|PRAGMA user_version)' \
      || true
  )"
  [[ "$migration_files" == "scripts/migrate_notification_destinations_v47.py" && -z "$schema_delta" ]] \
    || fail "current release does not contain only the explicit v47 migration"
  revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  revision_short="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)"
  receipt_path="$REMOTE_BASE/data/backups/migration-notification-destinations-v47-$revision.json"
  [[ -z "$(ssh "$REMOTE_HOST" test -e "$receipt_path" && printf present || true)" ]] \
    || fail "v47 migration receipt already exists for this release: $receipt_path"
  wait_for_workflow_success test-gate.yml "$revision" main
  remote_capacity_preflight

  RELEASE_TMP_DIR="$(mktemp -d -t inteliscope-migration.XXXXXX)"
  source_archive="$RELEASE_TMP_DIR/source.tar.gz"
  git -C "$ROOT_DIR" archive --format=tar.gz --output="$source_archive" "$revision"
  source_sha="$(shasum -a 256 "$source_archive" | awk '{print $1}')"
  REMOTE_RELEASE_STAGE="/tmp/inteliscope-migration-v47-$revision_short-$$"
  ssh "$REMOTE_HOST" mkdir -p "$REMOTE_RELEASE_STAGE"
  transfer_with_retry "$source_archive" "$REMOTE_HOST:$REMOTE_RELEASE_STAGE/source.tar.gz" \
    || fail "v47 migration source upload failed"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_RELEASE_STAGE" "$source_sha" <<'REMOTE'
set -euo pipefail
stage="$1"
expected_sha="$2"
[[ "$(sha256sum "$stage/source.tar.gz" | awk '{print $1}')" == "$expected_sha" ]]
REMOTE

  ssh "$REMOTE_HOST" bash -s -- \
    "$REMOTE_BASE" "$REMOTE_RELEASE_STAGE" "$receipt_path" "$revision" "$PUBLIC_URL" <<'REMOTE'
set -euo pipefail
base="$1"
stage="$2"
receipt_path="$3"
revision="$4"
public_url="$5"
database="$base/data/service.db"
backup_dir="$base/data/backups"
current_release="$(readlink -f "$base/current")"
env_before="$stage/env.before"
migration_backup=""

[[ -f "$base/.env" && -f "$database" && -d "$current_release" ]] \
  || { echo "canonical production runtime is incomplete" >&2; exit 1; }
! grep -q '^INTELISCOPE_PRE_MIGRATION_BACKUP=' "$base/.env" \
  || { echo "stale migration rollback setting must be resolved before v47" >&2; exit 1; }
[[ "$receipt_path" == "$backup_dir/"*.json && ! -e "$receipt_path" ]] \
  || { echo "migration receipt path is unsafe or already exists" >&2; exit 1; }
install -m 600 "$base/.env" "$env_before"
tar -xzf "$stage/source.tar.gz" -C "$stage"

validate_database() {
  python3 - "$database" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=30)
try:
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('database integrity check failed')
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise SystemExit('database foreign keys are invalid')
finally:
    connection.close()
PY
}

restart_current() {
  local version current_revision source_digest public_args=() source_args=()
  cd "$current_release"
  docker compose -f docker-compose.light.yml up -d --no-build --force-recreate \
    horizon-api horizon-worker
  version="$(grep '^INTELISCOPE_VERSION=' release-metadata.env | cut -d= -f2-)"
  current_revision="$(grep '^INTELISCOPE_BUILD_REVISION=' release-metadata.env | cut -d= -f2-)"
  source_digest="$(grep '^INTELISCOPE_SOURCE_DIGEST=' release-metadata.env | cut -d= -f2- || true)"
  [[ -n "$version" && -n "$current_revision" ]]
  [[ -z "$public_url" ]] || public_args=(--public-url "$public_url")
  [[ -z "$source_digest" ]] || source_args=(--expected-source-digest "$source_digest")
  python3 "$current_release/scripts/runtime_health.py" \
    --base-url http://127.0.0.1:8080 \
    --expected-version "$version" \
    --expected-revision "$current_revision" \
    "${source_args[@]}" \
    --api-container horizon-light-api \
    --worker-container horizon-light-worker \
    "${public_args[@]}" \
    --timeout 180 --interval 2
}

rollback_migration() {
  local status=$?
  trap - ERR INT TERM
  echo "v47 migration failed; restoring the existing runtime" >&2
  docker stop --time 20 horizon-light-worker horizon-light-api >/dev/null 2>&1 || true
  if [[ -n "$migration_backup" ]]; then
    [[ "$migration_backup" == "$backup_dir/"* && -f "$migration_backup" && ! -L "$migration_backup" \
      && "$(stat -c '%a' "$migration_backup")" == "600" ]] \
      || { echo "v47 rollback backup is invalid" >&2; exit 1; }
    (cd "$stage" && python3 - "$database" "$migration_backup" <<'PY'
import sys
from scripts.migrate_notification_destinations_v47 import _restore_database

_restore_database(sys.argv[1], sys.argv[2])
PY
    )
    validate_database
    [[ ! -f "$receipt_path" ]] || rm -- "$receipt_path"
  fi
  install -m 600 "$env_before" "$base/.env"
  restart_current || { echo "v47 rollback runtime is not healthy" >&2; exit 1; }
  exit "$status"
}

trap rollback_migration ERR INT TERM
docker stop --time 20 horizon-light-worker horizon-light-api
sleep 35
migration_result="$(cd "$stage" && python3 scripts/migrate_notification_destinations_v47.py \
  --data-dir "$base/data" --backup-dir "$backup_dir" --apply --services-stopped \
  --release-receipt "$receipt_path" --release-revision "$revision")"
read -r migration_backup written_receipt <<<"$(python3 -c '
import json, sys
result = json.loads(sys.stdin.read())
if result.get("status") != "applied":
    raise SystemExit("v47 migration did not apply")
backup = result.get("backup")
receipt = result.get("release_receipt")
if not isinstance(backup, str) or not isinstance(receipt, str):
    raise SystemExit("v47 migration response lacks evidence")
print(backup, receipt)
' <<<"$migration_result")"
[[ "$written_receipt" == "$receipt_path" ]]
validate_database
restart_current
trap - ERR INT TERM
rm -rf "$stage" || echo "v47 migration succeeded; temporary source cleanup needs attention" >&2
printf 'v47 migration ready: receipt=%s backup=%s\n' "$receipt_path" "$migration_backup"
REMOTE
  REMOTE_RELEASE_STAGE=""
  verified_backup="$(verify_notification_destinations_v47_receipt "$receipt_path" "$revision")"
  [[ -n "$verified_backup" ]] || fail "v47 receipt verification returned no backup"
  echo "v47 migration complete; release with --migration-receipt $receipt_path"
}

reissue_notification_destinations_v47_receipt() {
  local source_receipt="$1" source_revision revision receipt_path archive archive_sha stage
  require_commands
  require_release_identity
  [[ "$source_receipt" == "$REMOTE_BASE/data/backups/migration-notification-destinations-v47-"*.json ]] \
    || fail "source receipt must be a managed v47 migration receipt"
  source_revision="${source_receipt##*migration-notification-destinations-v47-}"
  source_revision="${source_revision%.json}"
  [[ "$source_revision" =~ ^[0-9a-f]{40}$ ]] || fail "source receipt has no full revision"
  revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  [[ "$source_revision" != "$revision" ]] || fail "source and target receipt revisions must differ"
  git -C "$ROOT_DIR" merge-base --is-ancestor "$source_revision" "$revision" \
    || fail "source migration revision is not an ancestor of the release"
  [[ -z "$(git -C "$ROOT_DIR" diff --name-only "$source_revision"..."$revision" -- \
    src/storage src/services frontend/src)" ]] \
    || fail "product or storage behavior changed after v47 migration; a receipt cannot be reissued"
  verify_notification_destinations_v47_receipt "$source_receipt" "$source_revision" >/dev/null
  receipt_path="$REMOTE_BASE/data/backups/migration-notification-destinations-v47-$revision.json"
  [[ -z "$(ssh "$REMOTE_HOST" test -e "$receipt_path" && printf present || true)" ]] \
    || fail "target release receipt already exists: $receipt_path"
  wait_for_workflow_success test-gate.yml "$revision" main
  RELEASE_TMP_DIR="$(mktemp -d -t inteliscope-v47-receipt.XXXXXX)"
  archive="$RELEASE_TMP_DIR/source.tar.gz"
  git -C "$ROOT_DIR" archive --format=tar.gz --output="$archive" "$revision"
  archive_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
  stage="/tmp/inteliscope-migration-v47-receipt-${revision:0:12}-$$"
  REMOTE_RELEASE_STAGE="$stage"
  ssh "$REMOTE_HOST" mkdir -p "$stage"
  transfer_with_retry "$archive" "$REMOTE_HOST:$stage/source.tar.gz" \
    || fail "v47 receipt source upload failed"
  ssh "$REMOTE_HOST" bash -s -- "$REMOTE_BASE" "$stage" "$archive_sha" \
    "$source_receipt" "$source_revision" "$receipt_path" "$revision" <<'REMOTE'
set -euo pipefail
base="$1"
stage="$2"
archive_sha="$3"
source_receipt="$4"
source_revision="$5"
receipt_path="$6"
revision="$7"
[[ "$(sha256sum "$stage/source.tar.gz" | awk '{print $1}')" == "$archive_sha" ]]
tar -xzf "$stage/source.tar.gz" -C "$stage"
(cd "$stage" && python3 scripts/migrate_notification_destinations_v47.py \
  --data-dir "$base/data" --reissue-from "$source_receipt" \
  --reissue-source-revision "$source_revision" \
  --release-receipt "$receipt_path" --release-revision "$revision")
rm -rf -- "$stage"
REMOTE
  REMOTE_RELEASE_STAGE=""
  verify_notification_destinations_v47_receipt "$receipt_path" "$revision" >/dev/null
  echo "v47 receipt reissued without changing the database: $receipt_path"
}
