from pathlib import Path


def test_nginx_exposes_exact_remote_mcp_route_without_basic_auth():
    site = Path("deploy/nginx/inteliscope-basic-auth.conf").read_text(encoding="utf-8")
    limits = Path("deploy/nginx/inteliscope-rate-limit.conf").read_text(encoding="utf-8")

    assert "limit_req_zone $binary_remote_addr zone=inteliscope_mcp:10m rate=120r/m;" in limits
    assert "limit_conn_zone $binary_remote_addr zone=inteliscope_mcp_connections:10m;" in limits
    assert "location = /mcp" in site
    mcp_location = site.split("location = /mcp", 1)[1].split("location /", 1)[0]
    assert "auth_basic off;" in mcp_location
    assert "client_max_body_size 256k;" in mcp_location
    assert "limit_req zone=inteliscope_mcp" in mcp_location
    assert "limit_conn inteliscope_mcp_connections 8;" in mcp_location
    assert "proxy_set_header Authorization $http_authorization;" in mcp_location
    assert "proxy_pass http://127.0.0.1:8080;" in mcp_location


def test_nginx_remote_mcp_runbook_keeps_production_writes_off_and_schema_v7():
    docs = Path("deploy/nginx/README_zh.md").read_text(encoding="utf-8")

    assert "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false" in docs
    assert "schema v7" in docs
    assert "只启动 `horizon-api`" in docs
