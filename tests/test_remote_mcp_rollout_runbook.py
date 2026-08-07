from pathlib import Path


def test_remote_mcp_readonly_rollout_uses_standard_release_and_is_reversible():
    runbook = Path("docs/dev/remote-mcp-readonly-rollout.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "release_vps.sh preflight",
        "release_vps.sh release",
        "HORIZON_REMOTE_MCP_ENABLED=true",
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false",
        "remote_mcp_read_canary.py verify",
        "remote_mcp_read_canary.py expect-unauthorized",
        "24 小时",
        "docker load",
    ):
        assert required in runbook

    assert "API + Worker" in runbook
    assert "不得在 VPS 构建、编译或测试本仓库" in runbook
    assert "不得整份覆盖当前 Nginx server block" in runbook
    assert "不要为 Remote MCP 设置 `HORIZON_REQUIRE_WORKER_FOR_READINESS=false`" in runbook
    assert "不得创建写 scope" in runbook
    assert "INTELISCOPE_MCP_TOKEN=<" not in runbook
