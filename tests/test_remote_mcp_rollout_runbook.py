from pathlib import Path


def test_remote_mcp_readonly_rollout_is_api_only_sanitized_and_reversible():
    runbook = Path("docs/dev/remote-mcp-readonly-rollout.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "prepare_service_deployment.py",
        "horizon-mcp-staging",
        "127.0.0.1:18080",
        "HORIZON_REMOTE_MCP_ENABLED=true",
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false",
        "HORIZON_REQUIRE_WORKER_FOR_READINESS=false",
        "remote_mcp_read_canary.py verify",
        "remote_mcp_read_canary.py expect-unauthorized",
        "24 小时",
        "schema v7",
    ):
        assert required in runbook

    assert "只启动 `horizon-api`" in runbook
    assert "不得启动 `horizon-worker`" in runbook
    assert "不得整份覆盖当前 Nginx server block" in runbook
    assert 'mkdir -p "$STAGING_ROOT/data" "$STAGING_ROOT/logs"' in runbook
    assert '-v "$STAGING_ROOT/logs:/app/logs"' in runbook
    assert '-v "$BASE/logs:/app/logs"' not in runbook
    assert "`/etc/nginx/sites-enabled/cfl.conf`" in runbook
    assert "docker stop horizon-light-api horizon-light-worker" in runbook
    assert "INTELISCOPE_MCP_TOKEN=<" not in runbook
