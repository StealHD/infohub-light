import json
from pathlib import Path

from src.models import Config


ROOT = Path(__file__).resolve().parents[1]


def test_up_latest_prefers_light_compose_and_does_not_start_scheduler_by_default():
    script = (ROOT / "scripts" / "up-latest.sh").read_text(encoding="utf-8")

    assert "docker-compose.light.yml" in script
    assert 'LIGHT_SERVICES=("horizon-api")' in script
    assert 'LIGHT_MANUAL_SERVICE="horizon"' in script
    light_branch = script.split('if [[ -f "docker-compose.light.yml" ]]', 1)[1].split("else", 1)[0]
    assert 'horizon-scheduler"' not in light_branch


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
