"""Private, schema-proven input-only plans for sampled Actor adaptation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from ..apify_actor_manifest import ActorManifestError, ManifestReference
from .discovery_manifest import validate_schema_proven_input
from .ports import DiscoveryRevision, FetchWindow, TargetSpec


_ACTOR_ID = re.compile(
    r"^(?:[A-Za-z0-9]{8,64}|[A-Za-z0-9][A-Za-z0-9._-]{0,62}[/~]"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,62})$"
)
_BUILD_NUMBER = re.compile(
    r"^(?:[0-9]|[1-9][0-9])\.(?:[0-9]|[1-9][0-9])"
    r"(?:\.(?:0|[1-9][0-9]{0,4}))$"
)


def create_input_plan(
    revision: DiscoveryRevision, input_template: Mapping[str, object]
) -> tuple[str | None, str | None]:
    """Canonicalize and prove an InputPlan against one exact Input Schema."""

    value = {
        "version": 1,
        "actor_id": revision.actor_id,
        "build_number": revision.build_number,
        "input": dict(input_template),
    }
    try:
        _validate_identity(value)
        _validate_template(value["input"])
    except (ActorManifestError, TypeError, ValueError):
        return None, "actorops_discovery_input_plan_invalid"
    error = validate_schema_proven_input(value["input"], revision.input_schema)
    if error:
        return None, error
    return json.dumps(value, sort_keys=True, separators=(",", ":")), None


def parse_input_plan(value: str | Mapping[str, object]) -> dict[str, object]:
    try:
        raw = json.loads(value) if isinstance(value, str) else dict(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ActorManifestError(
            "apify_input_plan_invalid", "Actor InputPlan is invalid"
        ) from None
    if set(raw) != {"version", "actor_id", "build_number", "input"}:
        raise ActorManifestError(
            "apify_input_plan_invalid", "Actor InputPlan has unknown fields"
        )
    try:
        _validate_identity(raw)
        _validate_template(raw["input"])
    except (ActorManifestError, TypeError, ValueError):
        raise ActorManifestError(
            "apify_input_plan_invalid", "Actor InputPlan failed validation"
        ) from None
    return raw


def input_plan_hash(value: str | Mapping[str, object]) -> str:
    plan = parse_input_plan(value)
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def render_input_plan(
    value: str | Mapping[str, object], target: TargetSpec, window: FetchWindow
) -> dict[str, Any]:
    plan = parse_input_plan(value)
    values = {
        "target.canonical_url": target.canonical_url,
        "target.native_id": target.native_id,
        "target.handle": target.handle,
        "runtime.max_items": window.max_items,
        "runtime.since_iso": window.since.isoformat(),
        "runtime.until_iso": window.until.isoformat() if window.until else None,
    }

    def render(node: Any) -> Any:
        if isinstance(node, Mapping):
            if "$ref" in node:
                try:
                    reference = ManifestReference.model_validate(node)
                except Exception:
                    raise ActorManifestError(
                        "apify_input_plan_invalid", "InputPlan reference is invalid"
                    ) from None
                resolved = values[reference.ref]
                if resolved is None:
                    raise ActorManifestError(
                        "apify_input_plan_reference_unavailable",
                        "InputPlan requires unavailable target context",
                    )
                return resolved
            return {str(key): render(value) for key, value in node.items()}
        if isinstance(node, list):
            return [render(value) for value in node]
        return node

    rendered = render(plan["input"])
    if not isinstance(rendered, dict):
        raise ActorManifestError(
            "apify_input_plan_invalid", "Rendered InputPlan must be an object"
        )
    return rendered


def _validate_identity(value: Mapping[str, object]) -> None:
    if value.get("version") != 1:
        raise ValueError("input plan version is unsupported")
    actor_id = value.get("actor_id")
    build_number = value.get("build_number")
    if not isinstance(actor_id, str) or not _ACTOR_ID.fullmatch(actor_id):
        raise ValueError("input plan actor identity is invalid")
    if not isinstance(build_number, str) or not _BUILD_NUMBER.fullmatch(build_number):
        raise ValueError("input plan Build identity is invalid")
    if not isinstance(value.get("input"), Mapping):
        raise ValueError("input plan template is invalid")


def _validate_template(value: object) -> None:
    """Bound an InputPlan before the exact Input Schema proof runs."""

    nodes = 0

    def visit(node: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 512 or depth > 12:
            raise ValueError("input plan exceeds structural limits")
        if node is None or isinstance(node, (bool, int, float)):
            if isinstance(node, float) and not math.isfinite(node):
                raise ValueError("input plan number is not finite")
            return
        if isinstance(node, str):
            if len(node) > 2048 or any(mark in node for mark in ("${", "{{", "}}", "<%", "%>", "://")):
                raise ValueError("input plan literal is unsafe")
            return
        if isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
            return
        if not isinstance(node, Mapping):
            raise ValueError("input plan contains a non-JSON value")
        if "$ref" in node:
            ManifestReference.model_validate(node)
            return
        for key, child in node.items():
            if not isinstance(key, str) or not key or len(key) > 128:
                raise ValueError("input plan key is invalid")
            normalized = re.sub(r"[^a-z0-9_]", "", key.casefold())
            if any(part in normalized for part in (
                "auth", "credential", "cookie", "header", "password", "proxy",
                "secret", "token", "apikey", "api_key", "webhook", "request",
                "javascript", "python", "eval", "function", "script", "command",
                "shell", "network", "code",
            )):
                raise ValueError("input plan contains a forbidden field")
            visit(child, depth + 1)

    if not isinstance(value, Mapping):
        raise ValueError("input plan must be an object")
    visit(value, 0)


__all__ = [
    "create_input_plan", "input_plan_hash", "parse_input_plan", "render_input_plan",
]
