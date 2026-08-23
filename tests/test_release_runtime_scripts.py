from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_normal_vps_release_reuses_main_ci_and_performs_bounded_cutover():
    script = (ROOT / "scripts" / "release_vps.sh").read_text(encoding="utf-8")

    assert "git fetch --prune origin main --tags" in script
    assert "local main must exactly match origin/main" in script
    assert "scripts/test_gate.py preflight" in script
    assert '--base "$base_ref" --head HEAD' in script
    assert "test-gate.yml" in script
    assert 'git -C "$ROOT_DIR" tag -a "$RELEASE_TAG"' in script
    assert "release-tag.yml" in script
    assert script.index("wait_for_workflow_success test-gate.yml") < script.index(
        'git -C "$ROOT_DIR" tag -a "$RELEASE_TAG"'
    )
    assert script.index("wait_for_workflow_success release-tag.yml") < script.rindex(
        '  deploy_remote_release "$release_id"'
    )
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
    assert script.index('install -m 600 "$migration_backup" "$base/data/service.db"') < script.index(
        'cd "$previous_release"'
    )
    assert 'docker image rm "$LOCAL_RELEASE_IMAGE"' in script


def test_normal_vps_release_does_not_run_full_database_scan_after_worker_start():
    script = (ROOT / "scripts" / "release_vps.sh").read_text(encoding="utf-8")
    cutover = script.split("trap rollback_cutover ERR INT TERM", 1)[1].split(
        "trap - ERR INT TERM", 1
    )[0]

    assert cutover.count("validate_database") == 1
    assert cutover.index("validate_database") < cutover.index(
        "horizon-api horizon-worker"
    )
    assert cutover.index("horizon-api horizon-worker") < cutover.index(
        'wait_runtime "$release_dir"'
    )
