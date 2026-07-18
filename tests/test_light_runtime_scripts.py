import json
import re
from pathlib import Path

from src.models import Config


ROOT = Path(__file__).resolve().parents[1]


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
    assert 'LIGHT_MANUAL_SERVICE="horizon"' in script
    light_branch = script.split('if [[ -f "docker-compose.light.yml" ]]', 1)[1].split("else", 1)[0]
    assert 'horizon-scheduler"' not in light_branch
    assert "INTELISCOPE_BUILD_REVISION" in script
    assert "/api/health/live" in script
    assert "/api/health/ready" in script
    health_position = script.index("/api/health/ready")
    assert health_position < script.index("docker image prune")
    assert health_position < script.index("docker builder prune")


def test_light_config_template_is_safe_and_valid():
    payload = json.loads((ROOT / "data" / "config.light.example.json").read_text(encoding="utf-8"))
    config = Config.model_validate(payload)

    assert config.ai.enabled is False
    assert config.webhook is None or config.webhook.enabled is False
    assert config.email is None or config.email.enabled is False
    assert config.sources.apify_social.enabled is False
    assert config.sources.openbb.enabled is False
    assert config.sources.ossinsight.enabled is False
    assert config.premium_analysis.enabled is False
    assert config.article_graph.enabled is False


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


def test_production_image_excludes_runtime_data_and_uses_release_identity():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY data ./data" not in dockerfile
    assert "INTELISCOPE_BUILD_REVISION" in dockerfile
    assert "INTELISCOPE_BUILT_AT" in dockerfile
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


def test_rc1_release_script_uses_clean_git_archive_and_staged_vps_cutover():
    script = (ROOT / "scripts" / "release_rc1.sh").read_text(encoding="utf-8")

    assert "git status --porcelain" in script
    assert "archive --format=tar.gz" in script
    assert "vps-tokyo" in script
    assert "${INTELISCOPE_DEPLOY_BASE:-/opt/inteliscope}" in script
    assert 'release_dir="$base/releases/$release_id"' in script
    assert "HORIZON_WEB_PORT 18080" in script
    assert "HORIZON_WEB_PORT 8080" in script
    assert "HORIZON_AUTH_SECURE_COOKIE false" in script
    assert "HORIZON_AUTH_SECURE_COOKIE true" in script
    assert "stop horizon-scheduler" in script
    assert "stop horizon-web" in script
    assert "up -d --no-build --force-recreate horizon-api horizon-worker" in script
    rollback = script.split("rollback_release() {", 1)[1].split("show_status()", 1)[0]
    assert "horizon-worker horizon-api" in rollback
    assert "start horizon-web" in rollback
    assert "start horizon-scheduler" not in rollback
    assert "docker image prune" not in script
    assert "docker builder prune" not in script
    local_gates = script.split("run_local_gates() {", 1)[1].split("validate_database_artifact()", 1)[0]
    assert "scripts/test_gate.py run --mode release" in local_gates
    assert "pytest -q" not in local_gates
    assert "node --test" not in local_gates


def test_test_gate_ci_runs_parallel_full_gates_and_conditional_release_checks():
    workflow = (ROOT / ".github" / "workflows" / "test-gate.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.12"' in workflow
    assert 'node-version: "22"' in workflow
    assert "impact:" in workflow
    assert "backend-full:" in workflow
    assert "frontend-full:" in workflow
    assert "--mode full --scope backend" in workflow
    assert "--mode full --scope frontend" in workflow
    assert "--mode release --scope e2e" in workflow
    assert "--mode release --scope smoke" in workflow
    assert "needs.impact.outputs.ui_impacted == 'true'" in workflow
    assert "retention-days: 7" in workflow
    assert "service_real_source_smoke" not in workflow
    assert "horizon-worker" not in workflow


def test_test_gate_compose_is_isolated_api_only_without_runtime_dependency_sync():
    compose = (ROOT / "docker-compose.test-gate.yml").read_text(encoding="utf-8")
    services = _compose_service_blocks(compose.split("\nnetworks:", 1)[0])

    assert set(services) == {"horizon-api"}
    assert 'entrypoint: ["uv", "run", "--no-sync", "horizon-api"]' in compose
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
    assert "不能替代应用登录" in docs
    assert "只想省事可以关闭应用内鉴权" not in docs


def test_compose_defaults_to_api_and_worker_but_not_scheduler():
    root_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    light_compose = (ROOT / "docker-compose.light.yml").read_text(encoding="utf-8")

    root_worker = root_compose.split("  horizon-worker:", 1)[1]
    light_worker = light_compose.split("  horizon-worker:", 1)[1].split("  horizon-scheduler:", 1)[0]
    root_api = root_compose.split("  horizon-api:", 1)[1].split("  horizon-worker:", 1)[0]
    light_api = light_compose.split("  horizon-api:", 1)[1].split("  horizon-worker:", 1)[0]
    root_scheduler = root_compose.split("  horizon-scheduler:", 1)[1].split("  horizon-web:", 1)[0]
    light_scheduler = light_compose.split("  horizon-scheduler:", 1)[1]

    assert 'profiles: ["worker"]' not in root_worker
    assert 'profiles: ["worker"]' not in light_worker
    assert 'profiles: ["scheduler"]' in root_scheduler
    assert 'profiles: ["scheduler"]' in light_scheduler
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
        assert 'profiles: ["scheduler"]' in services["horizon-scheduler"]
        assert (
            "HORIZON_SCHEDULE_POLL_SECONDS: "
            "${HORIZON_SCHEDULE_POLL_SECONDS:-30}"
        ) in services["horizon-worker"]

    assert "HORIZON_SCHEDULE_POLL_SECONDS=30" in env_example


def test_service_runtime_docs_require_owner_credentials_before_compose_startup():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (ROOT / "README_zh.md").read_text(encoding="utf-8")
    api_contract = (ROOT / "API_CONTRACT.md").read_text(encoding="utf-8")

    assert "Service API always requires an owner login" in env_example
    assert "HORIZON_AUTH_ENABLED only controls the legacy horizon-web service" in env_example
    assert "Default false keeps local development open" not in env_example
    assert "多人 Service API 始终要求登录" in readme
    assert "HORIZON_AUTH_ENABLED=false" in readme
    assert "不会让 Service API 免登录" in readme
    deployment = readme.split("部署步骤：", 1)[1].split("手动执行与检查：", 1)[0]
    credential_position = min(
        position
        for marker in ("HORIZON_AUTH_PASSWORD=", "HORIZON_AUTH_PASSWORD_HASH=")
        if (position := deployment.find(marker)) >= 0
    )
    assert credential_position < deployment.index("./scripts/up-latest.sh")
    assert "auth_not_configured" in api_contract
    assert "至少一个 enabled user" in api_contract
    assert "auth_not_configured" in readme
