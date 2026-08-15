import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from src.models import Config


ROOT = Path(__file__).resolve().parents[1]
PROJECT_VERSION = re.search(
    r'^version = "([^"]+)"',
    (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
    flags=re.MULTILINE,
).group(1)
LINKED_FIXTURE_VERSION = "99.99.99"


def _clean_runtime_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HORIZON_", "INTELISCOPE_"))
    }
    environment["INTELISCOPE_HEALTH_PYTHON"] = os.environ.get("PYTHON", "") or sys.executable
    environment["INTELISCOPE_HEALTH_TIMEOUT_SECONDS"] = "0.5"
    environment["INTELISCOPE_HEALTH_INTERVAL_SECONDS"] = "0"
    return environment


def _create_linked_worktree_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, str, str]:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    (primary / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "up-latest.sh", primary / "scripts" / "up-latest.sh")
    shutil.copy2(ROOT / "scripts" / "runtime_health.py", primary / "scripts" / "runtime_health.py")
    shutil.copy2(ROOT / "docker-compose.light.yml", primary / "docker-compose.light.yml")
    shutil.copy2(ROOT / "pyproject.toml", primary / "pyproject.toml")
    (primary / ".gitignore").write_text(".env\ndata/\nlogs/\n", encoding="utf-8")

    def git(*args: str, cwd: Path = primary) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    git("init", "-b", "main")
    git("config", "user.name", "Runtime Test")
    git("config", "user.email", "runtime-test@example.invalid")
    git(
        "add",
        ".gitignore",
        "scripts/up-latest.sh",
        "scripts/runtime_health.py",
        "docker-compose.light.yml",
        "pyproject.toml",
    )
    git("commit", "-m", "fixture")
    git("worktree", "add", "-b", "fixture", str(linked))
    (linked / "linked-marker.txt").write_text("linked-only\n", encoding="utf-8")
    linked_pyproject = (linked / "pyproject.toml").read_text(encoding="utf-8")
    (linked / "pyproject.toml").write_text(
        linked_pyproject.replace(
            f'version = "{PROJECT_VERSION}"',
            f'version = "{LINKED_FIXTURE_VERSION}"',
            1,
        ),
        encoding="utf-8",
    )
    git("add", "linked-marker.txt", "pyproject.toml", cwd=linked)
    git("commit", "-m", "linked revision", cwd=linked)

    (primary / ".env").write_text(
        "\n".join(
            (
                "HORIZON_BUILD_NO_CACHE=false",
                "HORIZON_PRUNE_OLD_IMAGES=false",
                "HORIZON_PRUNE_BUILD_CACHE=false",
                "HORIZON_PRUNE_OLD_LOCAL_BUILDS=false",
                "INTELISCOPE_VERSION=0.0.0-stale-runtime-version",
                "INTELISCOPE_BUILD_REVISION=stale-runtime-revision",
                "INTELISCOPE_BUILT_AT=stale-runtime-time",
                "INTELISCOPE_IMAGE=stale-runtime-image",
                "SECRET_SENTINEL=must-never-be-printed",
                "",
            )
        ),
        encoding="utf-8",
    )
    (primary / "data").mkdir()
    primary_revision = git("rev-parse", "--short=12", "HEAD").stdout.strip()
    linked_revision = git("rev-parse", "--short=12", "HEAD", cwd=linked).stdout.strip()
    assert primary_revision != linked_revision
    return primary, linked, primary_revision, linked_revision


def _install_fake_runtime_commands(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True)
    event_log = tmp_path / "events.log"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s | runtime=%s version=%s revision=%s built_at=%s image=%s\\n' \
  "$*" \
  "${INTELISCOPE_RUNTIME_ROOT-}" \
  "${INTELISCOPE_VERSION-}" \
  "${INTELISCOPE_BUILD_REVISION-}" \
  "${INTELISCOPE_BUILT_AT-}" \
  "${INTELISCOPE_IMAGE-}" >> "$FAKE_EVENT_LOG"
if [[ "$*" == *" stop "* && "${FAKE_STOP_FAIL-}" == "true" ]]; then
  exit 1
fi
if [[ "$*" == "image ls "* ]]; then
  printf '%b' "${FAKE_LOCAL_IMAGES-}"
fi
if [[ "${1-}" == "inspect" ]]; then
  if [[ "$*" == *".State.Running"* ]]; then
    if [[
      "${FAKE_RUNNING_MODE-}" == "api"
      && "$*" == *"horizon-light-api"*
    ]] || [[
      "${FAKE_RUNNING_MODE-}" == "worker"
      && "$*" == *"horizon-light-worker"*
    ]]; then
      printf 'true\\n'
    else
      printf 'false\\n'
    fi
  elif [[ "${FAKE_HEALTH_MODE-}" == "unhealthy" && "$*" == *"horizon-light-api"* ]]; then
    printf 'unhealthy\\n'
  elif [[ "${FAKE_HEALTH_MODE-}" == "final-unhealthy" && "$*" == *"horizon-light-api"* ]]; then
    probe_count="$(grep -c ".State.Health.Status.*horizon-light-api" "$FAKE_EVENT_LOG" || true)"
    if [[ "$probe_count" -ge 2 ]]; then
      printf 'unhealthy\\n'
    else
      printf 'healthy\\n'
    fi
  elif [[ "${FAKE_HEALTH_MODE-}" == "delayed" ]]; then
    probe_count="$(grep -c ".State.Health.Status.*${*: -1}" "$FAKE_EVENT_LOG" || true)"
    if [[ "$probe_count" -lt 3 ]]; then
      printf 'starting\\n'
    else
      printf 'healthy\\n'
    fi
  else
    printf 'healthy\\n'
  fi
fi
if [[ "$*" == *" ps" && "${FAKE_PS_FAIL-}" == "true" ]]; then
  exit 1
fi
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
printf 'curl %s\\n' "$url" >> "$FAKE_EVENT_LOG"
case "$url" in
  */api/health/live)
    deployed_revision="$FAKE_DEPLOYED_REVISION"
    live_count="$(grep -c '/api/health/live' "$FAKE_EVENT_LOG" || true)"
    if [[ "${FAKE_LIVE_DRIFT-}" == "true" && "$live_count" -ge 2 ]]; then
      deployed_revision="drifted-revision"
    fi
    printf '{"ok":true,"data":{"status":"live","version":"%s","revision":"%s"}}' \
      "$INTELISCOPE_VERSION" "$deployed_revision"
    ;;
  */api/health/ready)
    ready_count="$(grep -c '/api/health/ready' "$FAKE_EVENT_LOG" || true)"
    if [[ "${FAKE_READY_DRIFT-}" == "true" && "$ready_count" -ge 2 ]]; then
      printf '{"ok":false,"error":{"code":"worker_unavailable"},"data":{"worker_status":"missing"}}'
      exit 0
    fi
    case "${FAKE_READY_MODE-}" in
      migration-notification-v16)
        printf '{"ok":false,"error":{"code":"migration_required","message":"notification targets v16 migration must be applied"}}'
        ;;
      migration-notification-v15)
        printf '{"ok":false,"error":{"code":"migration_required","message":"notification channels v15 migration must be applied"}}'
        ;;
      migration-v14)
        printf '{"ok":false,"error":{"code":"migration_required","message":"Webhook providers v14 migration must be applied"}}'
        ;;
      migration-apify-v17)
        printf '{"ok":false,"error":{"code":"migration_required","message":"Apify ActorOps v15 migration must be applied"}}'
        ;;
      migration-apify-v18)
        printf '{"ok":false,"error":{"code":"migration_required","message":"Apify Discovery limits v16 migration must be applied"}}'
        ;;
      migration-apify-v19)
        printf '{"ok":false,"error":{"code":"migration_required","message":"Apify Actor Canary batch migration must be applied"}}'
        ;;
      migration-v11)
        printf '{"ok":false,"error":{"code":"migration_required","message":"content timeline v11 migration must be applied"}}'
        ;;
      migration-v13)
        printf '{"ok":false,"error":{"code":"migration_required","message":"Apify Actor routing v13 migration must be applied"}}'
        ;;
      migration-v4)
        printf '{"ok":false,"error":{"code":"migration_required","message":"user content v4 migration must be applied"}}'
        ;;
      migration-v2)
        printf '{"ok":false,"error":{"code":"migration_required","message":"user feed v2 migration must be applied"}}'
        ;;
      migration-unknown)
        printf '{"ok":false,"error":{"code":"migration_required","message":"future migration must be applied"}}'
        ;;
      worker-missing)
        printf '{"ok":false,"error":{"code":"worker_unavailable"},"data":{"worker_status":"missing"}}'
        ;;
      *)
        printf '{"ok":true,"data":{"status":"ready","worker_status":"ready"}}'
        ;;
    esac
    ;;
  */assets/*)
    if [[ "${FAKE_ASSET_MODE-}" == "asset-404" ]]; then
      exit 22
    fi
    printf 'console.log("fixture")'
    ;;
  */)
    if [[ "${FAKE_ASSET_MODE-}" == "missing" ]]; then
      printf '<main>fixture</main>'
    else
      printf '<script type="module" src="/assets/index-fixture.js"></script>'
    fi
    ;;
  *)
    exit 1
    ;;
esac
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    python = fake_bin / "python3"
    python.write_text(
        """#!/usr/bin/env bash
printf 'python3 %s\\n' "$*" >> "$FAKE_EVENT_LOG"
exit 99
""",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return fake_bin, event_log


def _compose_service_blocks(compose: str) -> dict[str, str]:
    matches = list(re.finditer(r"^  ([a-z0-9-]+):\n", compose, flags=re.MULTILINE))
    return {
        match.group(1): compose[match.start() : matches[index + 1].start()]
        if index + 1 < len(matches)
        else compose[match.start() :]
        for index, match in enumerate(matches)
    }


def test_up_latest_prefers_light_compose_and_does_not_start_scheduler_by_default():
    script = (ROOT / "scripts" / "up-latest.sh").read_text(encoding="utf-8")

    assert "docker-compose.light.yml" in script
    assert 'LIGHT_SERVICES=("horizon-api" "horizon-worker")' in script
    assert "LIGHT_MANUAL_SERVICE" not in script
    assert 'horizon-scheduler"' not in script
    assert 'docker-compose.yml"' not in script
    assert "--project-name infohub-light" in script
    assert "INTELISCOPE_BUILD_REVISION" in script
    assert "/api/health/live" in script
    assert "/api/health/ready" in script
    health_position = script.index("/api/health/ready")
    assert health_position < script.index("docker image prune")
    assert health_position < script.index("docker builder prune")
    health_helper_position = script.index("scripts/runtime_health.py")
    assert health_helper_position < script.index("docker image prune")
    assert health_helper_position < script.index("docker builder prune")
    assert 'HORIZON_PRUNE_OLD_LOCAL_BUILDS true' in script
    assert 'reference=inteliscope-service:local-*' in script
    assert script.index("container health changed before final completion verification") < script.index(
        "Removing ${#stale_local_images[@]} old local project image tag(s)"
    )


def test_up_latest_resolves_primary_runtime_from_a_linked_worktree(tmp_path: Path):
    primary, linked, primary_revision, linked_revision = _create_linked_worktree_fixture(
        tmp_path
    )

    linked_result = subprocess.run(
        ["bash", "scripts/up-latest.sh", "--dry-run"],
        cwd=linked,
        env=_clean_runtime_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    primary_result = subprocess.run(
        ["bash", "scripts/up-latest.sh", "--dry-run"],
        cwd=primary,
        env=_clean_runtime_environment(),
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"source root: {linked}" in linked_result.stdout
    assert f"runtime root: {primary}" in linked_result.stdout
    assert f"version: {LINKED_FIXTURE_VERSION}" in linked_result.stdout
    assert f"revision: {linked_revision}" in linked_result.stdout
    assert f"image: inteliscope-service:local-{linked_revision}" in linked_result.stdout
    assert "web port: 8080" in linked_result.stdout
    assert "Docker was not called" in linked_result.stdout
    assert "stale-runtime" not in linked_result.stdout
    assert "must-never-be-printed" not in linked_result.stdout

    assert f"source root: {primary}" in primary_result.stdout
    assert f"runtime root: {primary}" in primary_result.stdout
    assert f"version: {PROJECT_VERSION}" in primary_result.stdout
    assert f"revision: {primary_revision}" in primary_result.stdout
    assert linked_revision not in primary_result.stdout


def test_up_latest_rejects_invalid_runtime_inputs_before_docker(tmp_path: Path):
    primary, linked, _, _ = _create_linked_worktree_fixture(tmp_path)

    relative = subprocess.run(
        ["bash", "scripts/up-latest.sh", "--runtime-root", "relative", "--dry-run"],
        cwd=linked,
        env=_clean_runtime_environment(),
        capture_output=True,
        text=True,
    )
    assert relative.returncode != 0
    assert "--runtime-root must be an absolute path" in relative.stderr

    (primary / ".env").unlink()
    missing_env = subprocess.run(
        ["bash", "scripts/up-latest.sh", "--dry-run"],
        cwd=linked,
        env=_clean_runtime_environment(),
        capture_output=True,
        text=True,
    )
    assert missing_env.returncode != 0
    assert "runtime .env must be a regular, non-symlink file" in missing_env.stderr


def test_up_latest_fails_closed_without_light_compose(tmp_path: Path):
    _, linked, _, _ = _create_linked_worktree_fixture(tmp_path)
    (linked / "docker-compose.light.yml").unlink()

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh", "--dry-run"],
        cwd=linked,
        env=_clean_runtime_environment(),
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "required light Compose file is missing" in result.stderr


def test_up_latest_runs_one_verified_build_to_runtime_flow(tmp_path: Path):
    primary, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": revision,
            "FAKE_HEALTH_MODE": "delayed",
            "COMPOSE_PROJECT_NAME": "poisoned-project",
            "TMPDIR": str(event_log.parent),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh"],
        cwd=linked,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    events = event_log.read_text(encoding="utf-8")

    assert (
        f"compose --project-name infohub-light --env-file {primary}/.env "
        f"-f {linked}/docker-compose.light.yml "
        "build --pull horizon-api horizon-worker"
    ) in events
    assert "up -d --no-build --force-recreate --remove-orphans horizon-api horizon-worker" in events
    assert "horizon-scheduler" not in events
    assert (
        f"runtime={primary} version={LINKED_FIXTURE_VERSION} revision={revision} "
        f"built_at=stale-runtime-time image=inteliscope-service:local-{revision}"
    ) not in events
    assert (
        f"runtime={primary} version={LINKED_FIXTURE_VERSION} "
        f"revision={revision} built_at="
    ) in events
    assert f"image=inteliscope-service:local-{revision}" in events
    assert "stale-runtime" not in events
    assert f"curl http://127.0.0.1:8080/api/health/live" in events
    assert f"curl http://127.0.0.1:8080/api/health/ready" in events
    assert "docker inspect --format {{.State.Health.Status}} horizon-light-api" in events
    assert "docker inspect --format {{.State.Health.Status}} horizon-light-worker" in events
    assert events.count("docker inspect --format {{.State.Health.Status}} horizon-light-api") >= 3
    assert events.count("docker inspect --format {{.State.Health.Status}} horizon-light-worker") >= 3
    assert "curl http://127.0.0.1:8080/" in events
    assert "curl http://127.0.0.1:8080/assets/index-fixture.js" in events
    assert events.index(" build ") < events.index(" up -d ")
    assert events.index(" up -d ") < events.index("/api/health/live")
    api_inspect = "docker inspect --format {{.State.Health.Status}} horizon-light-api"
    worker_inspect = "docker inspect --format {{.State.Health.Status}} horizon-light-worker"
    assert events.index("/api/health/ready") < events.index(api_inspect)
    event_lines = events.splitlines()
    worker_inspect_index = next(
        index
        for index, line in enumerate(event_lines)
        if line.startswith(worker_inspect)
    )
    root_index = event_lines.index("curl http://127.0.0.1:8080/")
    assert worker_inspect_index < root_index
    assert events.index("/assets/index-fixture.js") < events.rindex(" ps |")
    assert "revision: " + revision in result.stdout
    assert "ready revision=" + revision in result.stdout
    assert "asset=index-fixture.js" in result.stdout
    assert "Local rebuild complete" in result.stdout
    assert "must-never-be-printed" not in result.stdout
    assert not (
        event_log.parent
        / f"inteliscope-infohub-light-{os.getuid()}.up-latest.lock"
    ).exists()


def test_up_latest_prunes_only_stale_local_project_images_after_final_verification(
    tmp_path: Path,
):
    _, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    current_image = f"inteliscope-service:local-{revision}"
    stale_image = "inteliscope-service:local-stale-revision"
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": revision,
            "FAKE_LOCAL_IMAGES": f"{current_image}\\n{stale_image}\\n",
            "HORIZON_PRUNE_OLD_LOCAL_BUILDS": "true",
            "TMPDIR": str(event_log.parent),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh"],
        cwd=linked,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    events = event_log.read_text(encoding="utf-8")

    assert "Removing 1 old local project image tag(s)" in result.stdout
    assert "docker image rm inteliscope-service:local-stale-revision" in events
    assert f"docker image rm {current_image}" not in events
    assert events.rindex(" ps |") < events.index("docker image ls")


def test_up_latest_stops_services_and_reports_explicit_migration(tmp_path: Path):
    primary, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    migration_cases = {
        "migration-notification-v16": "scripts/migrate_notification_targets_v16.py",
        "migration-notification-v15": "scripts/migrate_notification_channels_v15.py",
        "migration-v14": "scripts/migrate_webhook_providers_v14.py",
        "migration-apify-v17": "scripts/migrate_apify_actor_ops_v15.py",
        "migration-apify-v18": "scripts/migrate_apify_discovery_limits_v16.py",
        "migration-apify-v19": "scripts/migrate_apify_actor_canary_batches_v17.py",
        "migration-v13": "scripts/migrate_apify_actor_routing_v13.py",
        "migration-v11": "scripts/migrate_content_timeline_v11.py",
        "migration-v4": "scripts/migrate_user_content_v4.py",
        "migration-v2": "scripts/migrate_user_feed_v2.py",
        "migration-unknown": None,
    }
    for index, (mode, expected_script) in enumerate(migration_cases.items()):
        case_dir = tmp_path / f"case-{index}"
        fake_bin, event_log = _install_fake_runtime_commands(case_dir)
        env = _clean_runtime_environment()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "FAKE_EVENT_LOG": str(event_log),
                "FAKE_DEPLOYED_REVISION": revision,
                "FAKE_READY_MODE": mode,
                "TMPDIR": str(event_log.parent),
            }
        )

        result = subprocess.run(
            ["bash", "scripts/up-latest.sh"],
            cwd=linked,
            env=env,
            capture_output=True,
            text=True,
        )
        events = event_log.read_text(encoding="utf-8")

        assert result.returncode != 0
        assert (
            "Database migration is required; API and Worker are confirmed stopped."
            in result.stderr
        )
        assert f"--data-dir {primary}/data" in result.stderr or expected_script is None
        assert "stop horizon-api horizon-worker" in events
        assert "docker inspect --format {{.State.Running}} horizon-light-api" in events
        assert "docker inspect --format {{.State.Running}} horizon-light-worker" in events
        assert "python3 " not in events
        assert "Local rebuild complete" not in result.stdout
        if expected_script:
            assert expected_script in result.stderr
            assert f"--backup-dir {primary}/data/backups --apply" in result.stderr
        else:
            assert "Inspect http://127.0.0.1:8080/api/health/ready" in result.stderr


def test_up_latest_refuses_migration_from_a_different_revision(tmp_path: Path):
    _, linked, _, _ = _create_linked_worktree_fixture(tmp_path)
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": "different-revision",
            "FAKE_READY_MODE": "migration-v11",
            "TMPDIR": str(event_log.parent),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh"],
        cwd=linked,
        env=env,
        capture_output=True,
        text=True,
    )
    events = event_log.read_text(encoding="utf-8")

    assert result.returncode != 0
    assert "migration response did not come from the target revision" in result.stderr
    assert "stop horizon-api horizon-worker" not in events
    assert "migrate_content_timeline_v11.py" not in result.stderr
    assert "Local rebuild complete" not in result.stdout


def test_up_latest_does_not_claim_migration_stop_when_stop_fails(tmp_path: Path):
    _, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": revision,
            "FAKE_READY_MODE": "migration-v11",
            "FAKE_STOP_FAIL": "true",
            "TMPDIR": str(event_log.parent),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh"],
        cwd=linked,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "could not be stopped" in result.stderr
    assert "API and Worker are confirmed stopped." not in result.stderr
    assert "migrate_content_timeline_v11.py" not in result.stderr
    assert "Local rebuild complete" not in result.stdout


def test_up_latest_refuses_migration_while_a_container_is_still_running(
    tmp_path: Path,
):
    _, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    for index, running_mode in enumerate(("api", "worker")):
        case_dir = tmp_path / f"running-{index}"
        fake_bin, event_log = _install_fake_runtime_commands(case_dir)
        env = _clean_runtime_environment()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "FAKE_EVENT_LOG": str(event_log),
                "FAKE_DEPLOYED_REVISION": revision,
                "FAKE_READY_MODE": "migration-v11",
                "FAKE_RUNNING_MODE": running_mode,
                "TMPDIR": str(event_log.parent),
            }
        )

        result = subprocess.run(
            ["bash", "scripts/up-latest.sh"],
            cwd=linked,
            env=env,
            capture_output=True,
            text=True,
        )
        events = event_log.read_text(encoding="utf-8")

        assert result.returncode != 0
        assert "stopped-container verification failed" in result.stderr
        assert "API and Worker are confirmed stopped." not in result.stderr
        assert "migrate_content_timeline_v11.py" not in result.stderr
        assert "python3 " not in events
        assert "Local rebuild complete" not in result.stdout


def test_up_latest_rejects_concurrent_runtime_owner_before_docker(tmp_path: Path):
    primary, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    alternate_runtime = tmp_path / "alternate-runtime"
    alternate_runtime.mkdir()
    shutil.copy2(primary / ".env", alternate_runtime / ".env")
    (alternate_runtime / "data").mkdir()
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    lock_dir = (
        event_log.parent
        / f"inteliscope-infohub-light-{os.getuid()}.up-latest.lock"
    )
    lock_dir.mkdir()
    (lock_dir / "owner").write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": revision,
            "TMPDIR": str(event_log.parent),
        }
    )

    try:
        result = subprocess.run(
            [
                "bash",
                "scripts/up-latest.sh",
                "--runtime-root",
                str(alternate_runtime),
            ],
            cwd=linked,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "another local rebuild already owns the shared Docker project" in result.stderr
        assert not event_log.exists()
    finally:
        (lock_dir / "owner").unlink()
        lock_dir.rmdir()


def test_up_latest_recovers_a_stale_global_lock(tmp_path: Path):
    _, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    fake_bin, event_log = _install_fake_runtime_commands(tmp_path)
    lock_dir = (
        event_log.parent
        / f"inteliscope-infohub-light-{os.getuid()}.up-latest.lock"
    )
    lock_dir.mkdir()
    (lock_dir / "owner").write_text("pid=99999999\n", encoding="utf-8")
    env = _clean_runtime_environment()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "FAKE_DEPLOYED_REVISION": revision,
            "TMPDIR": str(event_log.parent),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/up-latest.sh"],
        cwd=linked,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Local rebuild complete" in result.stdout
    assert not lock_dir.exists()


def test_up_latest_requires_every_terminal_gate(tmp_path: Path):
    _, linked, _, revision = _create_linked_worktree_fixture(tmp_path)
    cases = (
        (
            {"FAKE_DEPLOYED_REVISION": "wrong-revision"},
            "runtime health verification failed",
            None,
        ),
        (
            {
                "FAKE_DEPLOYED_REVISION": revision,
                "FAKE_READY_MODE": "worker-missing",
            },
            "runtime health verification failed",
            None,
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_HEALTH_MODE": "unhealthy"},
            "container unhealthy",
            "docker inspect --format {{.State.Health.Status}} horizon-light-api",
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_ASSET_MODE": "missing"},
            "React frontend asset was not found",
            "curl http://127.0.0.1:8080/",
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_ASSET_MODE": "asset-404"},
            "runtime health verification failed",
            "curl http://127.0.0.1:8080/assets/index-fixture.js",
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_PS_FAIL": "true"},
            "",
            " ps |",
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_LIVE_DRIFT": "true"},
            "live revision changed before final completion verification",
            " ps |",
        ),
        (
            {"FAKE_DEPLOYED_REVISION": revision, "FAKE_READY_DRIFT": "true"},
            "API/Worker readiness changed before final completion verification",
            " ps |",
        ),
        (
            {
                "FAKE_DEPLOYED_REVISION": revision,
                "FAKE_HEALTH_MODE": "final-unhealthy",
            },
            "container health changed before final completion verification",
            " ps |",
        ),
    )
    for index, (overrides, expected_error, expected_event) in enumerate(cases):
        case_dir = tmp_path / f"gate-{index}"
        fake_bin, event_log = _install_fake_runtime_commands(case_dir)
        lock_dir = (
            event_log.parent
            / f"inteliscope-infohub-light-{os.getuid()}.up-latest.lock"
        )
        env = _clean_runtime_environment()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "FAKE_EVENT_LOG": str(event_log),
                "TMPDIR": str(event_log.parent),
                **overrides,
            }
        )

        result = subprocess.run(
            ["bash", "scripts/up-latest.sh"],
            cwd=linked,
            env=env,
            capture_output=True,
            text=True,
        )
        events = event_log.read_text(encoding="utf-8")

        assert result.returncode != 0
        assert expected_error in result.stderr
        if expected_event:
            assert expected_event in events
        if index < 2:
            assert ".State.Health.Status" not in events
        if overrides.get("FAKE_PS_FAIL") == "true":
            assert events.count("/api/health/live") == 1
        assert "Local rebuild complete" not in result.stdout
        assert not lock_dir.exists()


def test_light_compose_uses_explicit_runtime_root_and_port_8080():
    compose = (ROOT / "docker-compose.light.yml").read_text(encoding="utf-8")

    assert compose.count("${INTELISCOPE_RUNTIME_ROOT:-.}/data:/app/data") == 2
    assert compose.count("${INTELISCOPE_RUNTIME_ROOT:-.}/logs:/app/logs") == 2
    assert compose.count("${INTELISCOPE_RUNTIME_ROOT:-.}/.env:/app/.env:ro") == 2
    assert compose.count("${HORIZON_WEB_PORT:-8080}:8080") == 1
    assert "${HORIZON_WEB_PORT:-8081}:8080" not in compose


def test_light_config_template_is_safe_and_valid():
    payload = json.loads((ROOT / "data" / "config.light.example.json").read_text(encoding="utf-8"))
    config = Config.model_validate(payload)

    assert config.ai.enabled is False
    assert config.sources.apify_social.enabled is False
    assert config.sources.openbb.enabled is False
    assert config.sources.ossinsight.enabled is False


def test_light_compose_documents_worker_hardening_defaults():
    compose = (ROOT / "docker-compose.light.yml").read_text(encoding="utf-8")
    defaults = (ROOT / "project-defaults.yaml").read_text(encoding="utf-8")

    assert "HORIZON_WORKER_LEASE_SECONDS" in compose
    assert "HORIZON_WORKER_RETRY_BASE_SECONDS" in compose
    assert "HORIZON_JOB_RETENTION_DAYS" in compose
    assert "worker_lease_seconds" in defaults
    assert "worker_retry_base_seconds" in defaults
    assert "job_retention_days" in defaults


def test_compose_uses_delete_journal_only_for_local_bind_mount_runtime():
    root_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    light_compose = (ROOT / "docker-compose.light.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert root_compose.count(
        "HORIZON_SQLITE_JOURNAL_MODE: ${HORIZON_SQLITE_JOURNAL_MODE:-WAL}"
    ) == 2
    assert light_compose.count(
        "HORIZON_SQLITE_JOURNAL_MODE: ${HORIZON_SQLITE_JOURNAL_MODE:-DELETE}"
    ) == 2
    assert "HORIZON_SQLITE_JOURNAL_MODE=WAL" in env_example


def test_remote_mcp_subscription_writes_are_wired_off_by_default():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false" in env_example
    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        api = _compose_service_blocks(compose)["horizon-api"]
        assert (
            "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED: "
            "${HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED:-false}"
        ) in api


def test_apify_key_pool_is_wired_off_for_api_worker_and_release_smoke():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "HORIZON_APIFY_KEY_POOL_ENABLED=false" in env_example
    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        services = _compose_service_blocks(compose)
        for service_name in ("horizon-api", "horizon-worker"):
            assert (
                "HORIZON_APIFY_KEY_POOL_ENABLED: "
                "${HORIZON_APIFY_KEY_POOL_ENABLED:-false}"
            ) in services[service_name]
    release_smoke = (ROOT / "docker-compose.test-gate.yml").read_text(
        encoding="utf-8"
    )
    assert 'HORIZON_APIFY_KEY_POOL_ENABLED: "false"' in release_smoke


def test_openclaw_browser_chat_is_wired_off_with_a_loopback_default():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "HORIZON_OPENCLAW_CHAT_ENABLED=false" in env_example
    assert "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789" in env_example
    assert "HORIZON_OPENCLAW_IMAGE_IO_ENABLED=false" in env_example
    assert "HORIZON_OPENCLAW_MEDIA_ORIGINS=" in env_example
    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        api = _compose_service_blocks(compose)["horizon-api"]
        assert (
            "HORIZON_OPENCLAW_CHAT_ENABLED: "
            "${HORIZON_OPENCLAW_CHAT_ENABLED:-false}"
        ) in api
        assert (
            "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL: "
            "${HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL:-ws://127.0.0.1:18789}"
        ) in api
        assert (
            "HORIZON_OPENCLAW_IMAGE_IO_ENABLED: "
            "${HORIZON_OPENCLAW_IMAGE_IO_ENABLED:-false}"
        ) in api
        assert (
            "HORIZON_OPENCLAW_MEDIA_ORIGINS: "
            "${HORIZON_OPENCLAW_MEDIA_ORIGINS:-}"
        ) in api


def test_production_image_excludes_runtime_data_and_uses_release_identity():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY data ./data" not in dockerfile
    assert "INTELISCOPE_BUILD_REVISION" in dockerfile
    assert "INTELISCOPE_BUILT_AT" in dockerfile
    assert 'ENTRYPOINT ["/app/.venv/bin/horizon-api"]' in dockerfile
    assert 'CMD ["--host", "0.0.0.0", "--port", "8080"]' in dockerfile
    assert 'ENTRYPOINT ["uv", "run"' not in dockerfile
    assert "\ndata/\n" in dockerignore
    for forbidden in (
        "data/service.db",
        "data/service.db-*",
        "data/config.json",
        "data/backups/",
        "logs/",
        ".env",
    ):
        assert forbidden in dockerignore


def test_api_and_worker_share_one_versioned_service_image():
    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        services = _compose_service_blocks(compose)
        for service_name in ("horizon-api", "horizon-worker"):
            block = services[service_name]
            assert "INTELISCOPE_IMAGE" in block
            assert "INTELISCOPE_BUILD_REVISION" in block
            assert "INTELISCOPE_BUILT_AT" in block


def test_container_runtime_uses_preinstalled_venv_without_dependency_resolution():
    expected_entrypoints = {
        "horizon-api": "/app/.venv/bin/horizon-api",
        "horizon-worker": "/app/.venv/bin/horizon-worker",
    }

    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        services = _compose_service_blocks(compose)
        assert '"uv", "run"' not in compose
        for service_name, executable in expected_entrypoints.items():
            assert f'entrypoint: ["{executable}"]' in services[service_name]
        assert (
            "/app/.venv/bin/horizon-worker --healthcheck"
            in services["horizon-worker"]
        )


def test_rc1_release_script_uses_clean_git_archive_and_staged_vps_cutover():
    script = (ROOT / "scripts" / "release_rc1.sh").read_text(encoding="utf-8")

    assert "git status --porcelain" in script
    assert 'revision="$(git -C "$ROOT_DIR" rev-parse HEAD)"' in script
    assert "archive --format=tar.gz" in script
    assert "docker buildx build" in script
    assert 'platform="${INTELISCOPE_DEPLOY_PLATFORM:-linux/amd64}"' in script
    assert 'docker save "$image"' in script
    assert 'docker load -i "$image_archive"' in script
    assert '[[ "$loaded_arch" == amd64 ]]' in script
    assert script.count("docker run --rm --network none") == 2
    assert "--entrypoint /app/.venv/bin/horizon-api" in script
    assert "--entrypoint /app/.venv/bin/horizon-worker" in script
    assert "docker compose -f docker-compose.light.yml build" not in script
    assert "vps-tokyo" in script
    assert "${INTELISCOPE_DEPLOY_BASE:-/opt/inteliscope}" in script
    assert 'release_dir="$base/releases/$release_id"' in script
    assert "HORIZON_WEB_PORT 18080" in script
    assert "HORIZON_WEB_PORT 8080" in script
    assert "HORIZON_AUTH_SECURE_COOKIE false" in script
    assert "HORIZON_AUTH_SECURE_COOKIE true" in script
    assert "legacy scheduler must be stopped" in script
    assert "stop horizon-scheduler" not in script
    assert "stop horizon-web" not in script
    assert "up -d --no-build --force-recreate horizon-api horizon-worker" in script
    rollback = script.split("rollback_release() {", 1)[1].split("show_status()", 1)[0]
    assert "horizon-worker horizon-api" in rollback
    assert "start horizon-web" not in rollback
    assert "start horizon-scheduler" not in rollback
    assert "docker image prune" not in script
    assert "docker builder prune" not in script
    local_gates = script.split("run_local_gates() {", 1)[1].split("validate_database_artifact()", 1)[0]
    assert "scripts/test_gate.py preflight" in local_gates
    assert "scripts/test_gate.py run --mode release" in local_gates
    assert "pytest -q" not in local_gates
    assert "node --test" not in local_gates


def test_rsshub_bilibili_cookie_refresh_uses_an_isolated_browser_and_secret_store():
    script = (
        ROOT / "scripts" / "refresh_rsshub_bilibili_cookie.sh"
    ).read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "browser.newContext({ userAgent })" in script
    assert "https://www.bilibili.com/" in script
    assert "https://space.bilibili.com/1/dynamic" in script
    assert "https://api.bilibili.com/x/frontend/finger/spi" in script
    assert '["_uuid", "b_lsid", "b_nut", "buvid3", "buvid4", "buvid_fp"]' in script
    assert 'SecretStore("/app/data").set(' in script
    assert '"RSSHUB_BILIBILI_ANONYMOUS_COOKIE", value' in script
    assert "--entrypoint /app/.venv/bin/python" in script
    assert ".config/google-chrome" not in script
    assert ".mozilla" not in script
    assert "process.stdout.write" in script
    assert "console.log" not in script


def test_test_gate_ci_runs_parallel_full_gates_and_conditional_release_checks():
    workflow = (ROOT / ".github" / "workflows" / "test-gate.yml").read_text(encoding="utf-8")
    tag_workflow = (ROOT / ".github" / "workflows" / "release-tag.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.12"' in workflow
    assert 'node-version: "22"' in workflow
    assert "impact:" in workflow
    assert "backend-full:" in workflow
    assert "frontend-full:" in workflow
    assert "--mode full --scope backend" in workflow
    assert "--mode full --scope frontend" in workflow
    assert "--mode release --scope e2e" in workflow
    assert "--full-e2e" in workflow
    assert 'github.event_name }}" == "push"' in workflow
    assert "--mode release --scope smoke" in workflow
    assert "needs.impact.outputs.ui_impacted == 'true'" in workflow
    assert "needs.impact.outputs.backend_impacted == 'true'" in workflow
    assert "needs.impact.outputs.frontend_impacted == 'true'" in workflow
    assert "needs: [impact, frontend-full]" not in workflow
    assert 'tags: ["v*"]' not in workflow
    assert "retention-days: 7" in workflow
    assert workflow.count("include-hidden-files: true") == 4
    assert workflow.count("if-no-files-found: error") == 4
    assert "frontend/test-results/**/*" in workflow
    assert "frontend/playwright-report/**/*" in workflow
    assert "service_real_source_smoke" not in workflow
    assert 'tags: ["v*"]' in tag_workflow
    assert "actions/workflows/test-gate.yml/runs?head_sha=$GITHUB_SHA" in tag_workflow
    assert "git merge-base --is-ancestor" in tag_workflow
    assert "--mode release --scope smoke" in tag_workflow
    assert "--scope backend" not in tag_workflow
    assert "--scope frontend" not in tag_workflow
    assert "--scope e2e" not in tag_workflow
    assert "horizon-worker" not in workflow


def test_test_gate_compose_is_isolated_api_only_without_runtime_dependency_sync():
    compose = (ROOT / "docker-compose.test-gate.yml").read_text(encoding="utf-8")
    services = _compose_service_blocks(compose.split("\nnetworks:", 1)[0])

    assert set(services) == {"horizon-api"}
    assert 'entrypoint: ["/app/.venv/bin/horizon-api"]' in compose
    assert '"uv", "run"' not in compose
    assert "networks: [test-gate]" in compose
    assert "HORIZON_TEST_DATA_DIR" in compose
    assert "HORIZON_TEST_LOG_DIR" in compose
    assert "horizon-worker" not in compose
    assert "horizon-scheduler" not in compose
    assert "/app/.env" not in compose


def test_nginx_rc1_template_keeps_app_auth_and_rate_limits_login():
    site = (ROOT / "deploy" / "nginx" / "inteliscope-basic-auth.conf").read_text(
        encoding="utf-8"
    )
    rate_limit = (
        ROOT / "deploy" / "nginx" / "inteliscope-rate-limit.conf"
    ).read_text(encoding="utf-8")
    docs = (ROOT / "deploy" / "nginx" / "README_zh.md").read_text(encoding="utf-8")

    assert "limit_req_zone" in rate_limit
    assert "inteliscope_login" in rate_limit
    assert "location = /api/auth/login" in site
    assert "limit_req zone=inteliscope_login" in site
    assert "X-Content-Type-Options" in site
    assert "X-Frame-Options" in site
    assert "Referrer-Policy" in site
    assert "Content-Security-Policy" in site
    assert "connect-src 'self' ws://127.0.0.1:18789 ws://localhost:18789 wss:" in site
    assert "frame-ancestors 'none'" in site
    assert "不能替代应用登录" in docs
    assert "只想省事可以关闭应用内鉴权" not in docs


def test_compose_defaults_to_api_and_worker_but_not_scheduler():
    root_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    light_compose = (ROOT / "docker-compose.light.yml").read_text(encoding="utf-8")

    root_worker = root_compose.split("  horizon-worker:", 1)[1]
    light_worker = light_compose.split("  horizon-worker:", 1)[1]
    root_api = root_compose.split("  horizon-api:", 1)[1].split("  horizon-worker:", 1)[0]
    light_api = light_compose.split("  horizon-api:", 1)[1].split("  horizon-worker:", 1)[0]
    assert 'profiles: ["worker"]' not in root_worker
    assert 'profiles: ["worker"]' not in light_worker
    assert "horizon-scheduler:" not in root_compose
    assert "horizon-scheduler:" not in light_compose
    assert "horizon-web:" not in root_compose
    assert "horizon-web:" not in light_compose
    for compose in (root_compose, light_compose):
        assert "/api/health/ready" in compose
        assert "--healthcheck" in compose
    assert "HORIZON_REQUIRE_WORKER_FOR_READINESS" in root_api
    assert "HORIZON_REQUIRE_WORKER_FOR_READINESS" in light_api


def test_compose_wires_user_feed_schedule_polling_without_a_new_default_service():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for filename in ("docker-compose.yml", "docker-compose.light.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        services = _compose_service_blocks(compose)
        default_services = {
            name for name, block in services.items() if "profiles:" not in block
        }

        assert default_services == {"horizon-api", "horizon-worker"}
        assert set(services) == {"horizon-api", "horizon-worker"}
        assert (
            "HORIZON_SCHEDULE_POLL_SECONDS: "
            "${HORIZON_SCHEDULE_POLL_SECONDS:-30}"
        ) in services["horizon-worker"]
        assert (
            "HORIZON_SCHEDULE_POLL_ENABLED: "
            "${HORIZON_SCHEDULE_POLL_ENABLED:-true}"
        ) in services["horizon-worker"]

    assert "HORIZON_SCHEDULE_POLL_SECONDS=30" in env_example
    assert "HORIZON_SCHEDULE_POLL_ENABLED=true" in env_example


def test_service_runtime_docs_require_owner_credentials_before_compose_startup():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (ROOT / "README_zh.md").read_text(encoding="utf-8")
    api_contract = (ROOT / "docs/contracts/api/service-core.md").read_text(
        encoding="utf-8"
    )

    assert "Service API always requires an owner login" in env_example
    assert "HORIZON_AUTH_ENABLED" not in env_example
    assert "Default false keeps local development open" not in env_example
    assert "多人 Service API 始终要求登录" in readme
    assert "HORIZON_AUTH_ENABLED=false" not in readme
    deployment = readme.split("## 本地 Docker 启动", 1)[1].split("## 前端开发", 1)[0]
    credential_position = min(
        position
        for marker in ("HORIZON_AUTH_PASSWORD=", "HORIZON_AUTH_PASSWORD_HASH=")
        if (position := deployment.find(marker)) >= 0
    )
    assert credential_position < deployment.index("./scripts/up-latest.sh")
    assert "auth_not_configured" in api_contract
    assert "至少一个 enabled user" in api_contract
    assert "auth_not_configured" in readme
