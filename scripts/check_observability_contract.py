#!/usr/bin/env python3
"""Fail closed when production API/Worker logging contracts drift."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROTECTED_RUNTIME_FILES = (
    "src/api/actor_alert_routes.py",
    "src/api/actorops_v2_alias_routes.py",
    "src/api/agent_delegation_routes.py",
    "src/api/apify_key_pool_routes.py",
    "src/api/catalog_metadata_routes.py",
    "src/api/catalog_membership_routes.py",
    "src/api/feed_routes.py",
    "src/api/job_routes.py",
    "src/api/notification_routes.py",
    "src/api/notification_transport_routes.py",
    "src/api/schedule_routes.py",
    "src/api/secret_routes.py",
    "src/api/server.py",
    "src/api/subscription_routes.py",
    "src/api/user_routes.py",
    "src/ai/analyzer.py",
    "src/ai/enricher.py",
    "src/logging_utils.py",
    "src/mcp/remote_server.py",
    "src/observability_context.py",
    "src/services/catalog_source_runner.py",
    "src/services/job_queue.py",
    "src/services/notification_email_transport.py",
    "src/services/notification_telegram_transport.py",
    "src/services/notification_webhook_transport.py",
    "src/services/operation_log.py",
    "src/services/preferred_source_notifications.py",
    "src/services/source_avatar.py",
    "src/services/workspace_telegram_transport.py",
    "src/services/worker.py",
    "src/services/worker_cycle.py",
    "src/services/worker_finalization.py",
    "src/services/worker_feed_handler.py",
    "src/services/worker_handlers.py",
    "src/services/worker_lifecycle.py",
    "src/services/worker_media_publication.py",
    "src/services/worker_migration_gate.py",
    "src/services/worker_post_commit.py",
)
MUTATION_METHODS = {"post", "put", "patch", "delete"}
DISALLOWED_LOGGING_CALLS = {
    "addHandler",
    "basicConfig",
    "dictConfig",
    "FileHandler",
    "RotatingFileHandler",
    "TimedRotatingFileHandler",
}
REQUIRED_WORKER_EVENTS = {
    ("job", "claim"),
    ("job", "finish"),
    ("job", "worker_boundary"),
    ("job", "lease_recovery"),
    ("job", "invalidate"),
    ("acquisition", "source_result"),
    ("source", "avatar_cache"),
    ("notification", "dispatch"),
}


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _constant_string(node: ast.AST | None) -> str | None:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _constant_strings(node: ast.AST | None) -> set[str]:
    if (value := _constant_string(node)) is not None:
        return {value}
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        values = {_constant_string(element) for element in node.elts}
        return (
            {value for value in values if value is not None}
            if None not in values
            else set()
        )
    return set()


def _literal_dict_keys(tree: ast.Module, name: str) -> set[str]:
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and target.id == name
            and isinstance(value, ast.Dict)
        ):
            return {
                key
                for raw_key in value.keys
                if (key := _constant_string(raw_key)) is not None
            }
    return set()


def _mutation_route_map(tree: ast.Module) -> set[tuple[str, str]]:
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "MUTATION_OPERATION_ROUTES"
            and isinstance(value, ast.Dict)
        ):
            routes: set[tuple[str, str]] = set()
            for raw_key in value.keys:
                if not isinstance(raw_key, ast.Tuple) or len(raw_key.elts) != 2:
                    continue
                method = _constant_string(raw_key.elts[0])
                route = _constant_string(raw_key.elts[1])
                if method and route:
                    routes.add((method, route))
            return routes
    return set()


def _decorated_mutation_routes(
    tree: ast.Module,
) -> list[tuple[str, str, int]]:
    routes: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                not isinstance(decorator, ast.Call)
                or not isinstance(decorator.func, ast.Attribute)
                or not isinstance(decorator.func.value, ast.Name)
                or decorator.func.attr not in MUTATION_METHODS
                or not decorator.args
            ):
                continue
            route = _constant_string(decorator.args[0])
            if route is not None:
                routes.append(
                    (decorator.func.attr.upper(), route, decorator.lineno)
                )
    return routes


def _registered_mutation_routes(
    tree: ast.Module,
) -> list[tuple[str, str, int]]:
    routes: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Attribute)
            or node.func.attr != "add_api_route"
            or not node.args
        ):
            continue
        route = _constant_string(node.args[0])
        methods_node = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "methods"
            ),
            None,
        )
        if route is None:
            continue
        for method in _constant_strings(methods_node):
            if method.lower() in MUTATION_METHODS:
                routes.append((method.upper(), route, node.lineno))
    return routes


def _api_mutation_routes(tree: ast.Module) -> list[tuple[str, str, int]]:
    return [
        *_decorated_mutation_routes(tree),
        *_registered_mutation_routes(tree),
    ]


def _operation_event_pairs(tree: ast.Module) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or _call_name(node)
            not in {"safe_emit_operation_event", "emit_operation_event"}
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        category = _constant_string(keywords.get("category"))
        action = _constant_string(keywords.get("action"))
        if category and action:
            pairs.add((category, action))
    return pairs


def _dispatched_worker_job_types(tree: ast.Module) -> set[str]:
    dispatched: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or node.name != "_run_job"
        ):
            continue
        for candidate in ast.walk(node):
            if (
                isinstance(candidate, ast.Compare)
                and len(candidate.ops) == 1
                and len(candidate.comparators) == 1
            ):
                left = candidate.left
                right = candidate.comparators[0]
                operator = candidate.ops[0]
                if isinstance(left, ast.Name) and left.id == "job_type":
                    if isinstance(operator, (ast.Eq, ast.In)):
                        dispatched.update(_constant_strings(right))
                elif (
                    isinstance(right, ast.Name)
                    and right.id == "job_type"
                    and isinstance(operator, ast.Eq)
                ):
                    dispatched.update(_constant_strings(left))
    return dispatched


def source_violations(
    relative: str,
    source: str,
    *,
    mutation_routes: set[tuple[str, str]] | None = None,
    worker_event_pairs: set[tuple[str, str]] | None = None,
) -> list[Violation]:
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        return [
            Violation(
                relative,
                int(exc.lineno or 1),
                "OBS000",
                "protected runtime file is not valid Python",
            )
        ]
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "print":
            violations.append(
                Violation(
                    relative,
                    node.lineno,
                    "OBS001",
                    "direct print is forbidden in the production API/Worker path",
                )
            )
        if (
            relative != "src/logging_utils.py"
            and name in DISALLOWED_LOGGING_CALLS
        ):
            violations.append(
                Violation(
                    relative,
                    node.lineno,
                    "OBS002",
                    "logging handlers/configuration belong only in src/logging_utils.py",
                )
            )
    if relative == "src/api/server.py":
        uvicorn_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "uvicorn"
            and node.func.attr == "run"
        ]
        if len(uvicorn_calls) != 1:
            violations.append(
                Violation(
                    relative,
                    1,
                    "OBS003",
                    "API must have exactly one managed uvicorn.run entrypoint",
                )
            )
        for call in uvicorn_calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
            if not (
                isinstance(keywords.get("log_config"), ast.Constant)
                and keywords["log_config"].value is None
                and isinstance(keywords.get("access_log"), ast.Constant)
                and keywords["access_log"].value is False
            ):
                violations.append(
                    Violation(
                        relative,
                        call.lineno,
                        "OBS004",
                        "uvicorn must use log_config=None and access_log=False",
                    )
                )
    if relative.startswith("src/api/"):
        mapped = (
            mutation_routes
            if mutation_routes is not None
            else _mutation_route_map(tree)
        )
        for method, route, line in _api_mutation_routes(tree):
            if (method, route) not in mapped:
                violations.append(
                    Violation(
                        relative,
                        line,
                        "OBS005",
                        f"{method} {route} has no MUTATION_OPERATION_ROUTES entry",
                    )
                )
    if relative == "src/services/worker.py":
        policy = _literal_dict_keys(tree, "WORKER_JOB_TRACE_POLICY")
        dispatched = _dispatched_worker_job_types(tree)
        for missing in sorted(dispatched - policy):
            violations.append(
                Violation(
                    relative,
                    1,
                    "OBS006",
                    f"Worker job type {missing!r} has no trace policy",
                )
            )
        observed_events = (
            worker_event_pairs
            if worker_event_pairs is not None
            else _operation_event_pairs(tree)
        )
        for category, action in sorted(REQUIRED_WORKER_EVENTS - observed_events):
            violations.append(
                Violation(
                    relative,
                    1,
                    "OBS007",
                    f"Worker is missing required {category}/{action} event",
                )
            )
    return violations


def check_repository(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    api_files = {
        path.relative_to(root).as_posix()
        for path in (root / "src" / "api").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    relatives = sorted({*PROTECTED_RUNTIME_FILES, *api_files})
    server_path = root / "src" / "api" / "server.py"
    mapped_mutations = set().union(
        *(
            _mutation_route_map(
                ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            )
            for relative in api_files
            if (path := root / relative).is_file()
        )
    )
    worker_event_pairs: set[tuple[str, str]] = set()
    for relative in (
        "src/services/worker.py",
        "src/services/worker_actor_canary_handler.py",
        "src/services/worker_actor_discovery_ai.py",
        "src/services/worker_actor_discovery_handler.py",
        "src/services/worker_actor_validation_handler.py",
        "src/services/worker_cycle.py",
        "src/services/worker_finalization.py",
        "src/services/worker_feed_handler.py",
        "src/services/worker_handlers.py",
        "src/services/worker_lifecycle.py",
        "src/services/worker_media_publication.py",
        "src/services/worker_post_commit.py",
    ):
        path = root / relative
        if path.is_file():
            worker_event_pairs.update(
                _operation_event_pairs(
                    ast.parse(path.read_text(encoding="utf-8"), filename=relative)
                )
            )
    for relative in relatives:
        path = root / relative
        if not path.is_file():
            violations.append(
                Violation(
                    relative,
                    1,
                    "OBS008",
                    "protected runtime file is missing",
                )
            )
            continue
        violations.extend(
            source_violations(
                relative,
                path.read_text(encoding="utf-8"),
                mutation_routes=(
                    mapped_mutations
                    if relative.startswith("src/api/")
                    else None
                ),
                worker_event_pairs=(
                    worker_event_pairs
                    if relative == "src/services/worker.py"
                    else None
                ),
            )
        )
    return sorted(
        violations,
        key=lambda item: (item.path, item.line, item.code, item.message),
    )


def _render(violations: Iterable[Violation]) -> str:
    return "\n".join(violation.render() for violation in violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    violations = check_repository(args.root.resolve())
    if violations:
        sys.stderr.write(_render(violations) + "\n")
        return 1
    print("observability contract: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
