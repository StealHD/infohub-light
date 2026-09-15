from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_normal_vps_release_keeps_runtime_protection_without_ci_waits():
    script = (ROOT / "scripts" / "release_vps.sh").read_text(encoding="utf-8")

    assert "git fetch --prune origin main --tags" in script
    assert "local main must exactly match origin/main" in script
    assert "scripts/test_gate.py preflight" in script
    assert '--base "$base_ref" --head HEAD' in script
    fast = (ROOT / "scripts/release_fast.sh").read_text()
    assert "wait_for_workflow_success" not in script + fast
    assert "test-gate.yml" not in script + fast
    assert "release-tag.yml" not in script + fast
    assert 'release() {\n  release_fast\n}' in script
    assert fast.index('  deploy_remote_release "$release_id"') < fast.index('git -C "$ROOT_DIR" tag -a')
    assert "docker buildx build" in script
    assert '--platform "$PLATFORM"' in script
    assert 'docker save "$image"' in script
    assert script.count("docker run --rm --network none") == 2
    assert 'transfer_with_retry "$archive"' in script
    assert 'transfer_with_retry "$image_archive"' in script
    assert "rsync --partial -az" in script
    assert "source.backup(destination)" in script
    assert 'install -m 600 "$base/.env"' in script
    assert 'os.chmod(sys.argv[2], 0o600)' in script
    assert 'docker load -i "$remote_stage/image.tar.gz"' in script
    assert "docker compose -f docker-compose.light.yml build" not in script
    assert "sleep 35" not in script
    assert "docker stop --time 20 horizon-light-worker" in script
    assert "horizon-api horizon-worker" in script
    assert "scripts/runtime_health.py" in script
    assert "--api-container horizon-light-api" in script
    assert "--worker-container horizon-light-worker" in script
    assert "rollback_cutover" in script
    assert script.count("trap rollback_cutover ERR INT TERM") == 1
    assert "trap - ERR INT TERM" in script
    assert "rollback restored healthy runtime" in script
    assert "rollback failed; previous runtime is not healthy" in script
    assert "rollback failed; canonical environment could not be restored" in script
    assert 'install -m 600 "$backup_dir/env.before" "$base/.env" || true' not in script
    assert 'wait_runtime "$previous_release" "$public_url"' in script
    assert "INTELISCOPE_PRE_MIGRATION_BACKUP" in script
    assert 'source "$ROOT_DIR/scripts/release_v47.sh"' in script
    assert 'keeping the additive v47 database and all writes made after migration' in script
    assert 'set_env INTELISCOPE_PRE_MIGRATION_BACKUP "$migration_backup"' not in script
    assert script.index('install -m 600 "$legacy_migration_backup" "$base/data/service.db"') < script.index(
        'cd "$previous_release"'
    )
    assert 'docker image rm "$LOCAL_RELEASE_IMAGE"' in script
    assert "remote_capacity_preflight" in script
    assert "available_kib < required_kib" in script
    assert "package_kib + database_kib + 524288" in script
    assert "8388608" not in script
    assert 'REMOTE_RELEASE_STAGE="/tmp/inteliscope-release-$release_id"' in fast
    assert '[[ "$stage" =~ ^/tmp/inteliscope-(release|migration)-[A-Za-z0-9._-]+$ ]]' in script
    assert 'rm -rf -- "$stage"' in script
    assert 'migration_receipt="${10:-}"' in script
    assert 'migration_backup="${11:-}"' in script
    package = script.split("build_package_and_upload() {", 1)[1].split("deploy_remote_release() {", 1)[0]
    assert package.count('require_frozen_release_source "$revision_full"') == 2
    assert package.index('require_frozen_release_source "$revision_full"') < package.index("docker buildx build")
    assert package.index("docker buildx build") < package.rindex('require_frozen_release_source "$revision_full"')
    rollback = script.split("rollback_release() {", 1)[1].split("show_status() {", 1)[0]
    assert 'set_env INTELISCOPE_SOURCE_DIGEST "$source_digest"' in rollback
    assert "sed -i '/^INTELISCOPE_SOURCE_DIGEST=/d'" in rollback
    assert 'source_args=(--expected-source-digest "$source_digest")' in rollback


def test_normal_vps_release_preserves_active_jobs_and_does_not_scan_after_worker_start():
    script = (ROOT / "scripts" / "release_vps.sh").read_text(encoding="utf-8")
    cutover = script.split("trap rollback_cutover ERR INT TERM", 1)[1].split(
        "trap - ERR INT TERM", 1
    )[0]

    assert "active_jobs" not in script
    assert "Queued and running jobs are durable." in script
    assert cutover.count("validate_database") == 1
    assert cutover.index('docker stop --time 20 horizon-light-worker horizon-light-api') < cutover.index(
        "validate_database"
    ) < cutover.index("source.backup(destination)")
    assert cutover.index("validate_database") < cutover.index(
        "horizon-api horizon-worker"
    )
    assert cutover.index("horizon-api horizon-worker") < cutover.index(
        'wait_runtime "$release_dir"'
    )


def test_live_v47_receipt_verification_checks_schema_without_scanning_the_database():
    helper = (ROOT / "scripts" / "release_v47.sh").read_text(encoding="utf-8")
    online = helper.split("verify_notification_destinations_v47_receipt() {", 1)[1].split(
        "migrate_notification_destinations_v47() {", 1
    )[0]
    assert "schema_migrations WHERE version=47" in online
    assert "PRAGMA table_info" in online
    assert "PRAGMA integrity_check" not in online
    assert "PRAGMA foreign_key_check" not in online


def test_rc1_release_freezes_and_propagates_the_build_source_identity():
    script = (ROOT / "scripts" / "release_rc1.sh").read_text(encoding="utf-8")
    prepare = script.split("prepare_release() {", 1)[1].split("promote_release() {", 1)[0]

    assert prepare.count('require_frozen_release_source "$revision"') == 2
    assert prepare.index('require_frozen_release_source "$revision"') < prepare.index("docker buildx build")
    assert prepare.index("docker buildx build") < prepare.rindex('require_frozen_release_source "$revision"')
    assert '--build-arg "INTELISCOPE_SOURCE_DIGEST=$source_digest"' in prepare
    assert 'loaded_source_digest="$(' in prepare
    assert '[[ "$loaded_source_digest" == "$source_digest" ]]' in prepare
    assert 'set_env INTELISCOPE_SOURCE_DIGEST "$source_digest"' in prepare
