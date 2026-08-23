from __future__ import annotations

import ast
from pathlib import Path

from src.mcp.remote_server import (
    AgentDelegationTokenVerifier,
    DelegationRateLimiter,
    ExactMCPPathApp,
    RemoteMCPApplication,
    SafeRemoteMCP,
    create_remote_mcp,
)
from src.mcp.remote_diagnostics import RemoteMCPDiagnostics
from src.mcp.remote_service import RemoteMCPNotFound, RemoteMCPReadService


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "src" / "mcp"


def _source(name: str) -> str:
    return (MCP_ROOT / name).read_text(encoding="utf-8")


def _registered_tools(name: str) -> set[str]:
    tree = ast.parse(_source(name))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        )
    }


def _remote_dependency_graph() -> dict[str, set[str]]:
    modules = {path.stem: path for path in MCP_ROOT.glob("remote_*.py")}
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 1
                and node.module in modules
            ):
                graph[name].add(node.module)
    return graph


def test_remote_server_is_a_small_explicit_composition_facade() -> None:
    source = _source("remote_server.py")

    assert len(source.splitlines()) <= 200
    assert "@server.tool" not in source
    assert "import *" not in source
    assert "register_read_tools(server, context)" in source
    assert "register_subscription_tools(server, context)" in source
    assert "register_diagnostic_tools(server, context)" in source

    assert AgentDelegationTokenVerifier.__module__ == "src.mcp.remote_auth"
    assert DelegationRateLimiter.__module__ == "src.mcp.remote_rate_limit"
    assert ExactMCPPathApp.__module__ == "src.mcp.remote_http"
    assert RemoteMCPApplication.__module__ == "src.mcp.remote_http"
    assert SafeRemoteMCP.__module__ == "src.mcp.remote_call_runtime"
    assert create_remote_mcp.__module__ == "src.mcp.remote_server"


def test_tool_registration_has_exactly_three_one_way_categories() -> None:
    read_tools = _registered_tools("remote_read_tools.py")
    subscription_tools = _registered_tools("remote_subscription_tools.py")
    diagnostic_tools = _registered_tools("remote_diagnostic_tools.py")

    assert read_tools == {
        "get_my_feed",
        "get_item",
        "list_subscriptions",
        "source_health",
        "list_jobs",
        "get_job",
        "get_source_setup_guide",
        "search_bilibili_users",
        "resolve_source",
        "list_available_sources",
    }
    assert subscription_tools == {
        "prepare_create_subscription",
        "prepare_update_subscription",
        "prepare_delete_subscription",
        "apply_subscription_change",
    }
    assert diagnostic_tools == {
        "diagnose_source",
        "diagnose_job",
        "query_operation_logs",
    }
    assert len(read_tools | subscription_tools | diagnostic_tools) == 17

    for name in (
        "remote_read_tools.py",
        "remote_subscription_tools.py",
        "remote_diagnostic_tools.py",
    ):
        source = _source(name)
        assert "ServiceStore" not in source
        assert "remote_server" not in source


def test_remote_audit_keeps_the_legacy_logger_name() -> None:
    assert 'logging.getLogger("src.mcp.remote_server")' in _source("remote_audit.py")


def test_read_service_is_an_explicit_focused_composition_facade() -> None:
    source = _source("remote_service.py")

    assert len(source.splitlines()) <= 200
    assert "import *" not in source
    assert "SELECT " not in source
    assert "RemoteMCPFeedReadService(store)" in source
    assert "RemoteMCPSubscriptionReadService(store)" in source
    assert "RemoteMCPJobReadService(store)" in source
    assert RemoteMCPReadService.__module__ == "src.mcp.remote_service"
    assert RemoteMCPNotFound.__module__ == "src.mcp.remote_read_projection"


def test_diagnostics_facade_composes_pure_projection_modules() -> None:
    facade = _source("remote_diagnostics.py")

    assert len(facade.splitlines()) <= 200
    assert "import *" not in facade
    assert "SELECT " not in facade
    assert "RemoteMCPDiagnosticRecords(" in facade
    assert RemoteMCPDiagnostics.__module__ == "src.mcp.remote_diagnostics"

    for name in (
        "remote_diagnostic_classification.py",
        "remote_diagnostic_evidence.py",
        "remote_diagnostic_projection.py",
        "remote_diagnostic_sanitization.py",
    ):
        source = _source(name)
        assert "ServiceStore" not in source
        assert ".connect()" not in source
        assert "JobQueue" not in source
        assert "RuntimeStatusService" not in source
        assert "httpx" not in source
        assert "requests" not in source


def test_remote_mcp_modules_have_no_dependency_cycles() -> None:
    graph = _remote_dependency_graph()
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            start = active.index(module)
            cycle = " -> ".join([*active[start:], module])
            raise AssertionError(f"Remote MCP dependency cycle: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
