"""Schema-proven lower bounds for bounded Actor item-limit inputs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


MAX_RUNTIME_ITEMS = 100
_RUNTIME_LIMIT_REF = {"$ref": "runtime.max_items"}


def runtime_limit_template(raw_schema: object) -> tuple[object | None, str | None]:
    """Return a safe runtime reference or its exact schema-required floor."""

    if not isinstance(raw_schema, Mapping):
        return dict(_RUNTIME_LIMIT_REF), None
    minimum = raw_schema.get("minimum")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
        return dict(_RUNTIME_LIMIT_REF), None
    types = _schema_types(raw_schema)
    value: int | float = math.ceil(float(minimum)) if "integer" in types else float(minimum)
    if value <= 1:
        return dict(_RUNTIME_LIMIT_REF), None
    maximum = raw_schema.get("maximum")
    if (
        value > MAX_RUNTIME_ITEMS
        or (
            isinstance(maximum, (int, float))
            and not isinstance(maximum, bool)
            and value > float(maximum)
        )
    ):
        return None, "actorops_discovery_input_minimum_exceeds_runtime_limit"
    return value, None


def normalize_runtime_limit_refs(
    template: Mapping[str, object], schema: Mapping[str, object]
) -> tuple[dict[str, object] | None, str | None]:
    """Raise only exact runtime item-limit refs to their public Schema floor."""

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return dict(template), None
    normalized: dict[str, object] = {}
    for key, value in template.items():
        raw_schema = properties.get(key)
        resolved, error = _normalize_node(value, raw_schema)
        if error:
            return None, error
        normalized[str(key)] = resolved
    return normalized, None


def _normalize_node(value: object, raw_schema: object) -> tuple[Any, str | None]:
    if value == _RUNTIME_LIMIT_REF:
        return runtime_limit_template(raw_schema)
    if isinstance(value, list):
        items = raw_schema.get("items") if isinstance(raw_schema, Mapping) else None
        children: list[object] = []
        for child in value:
            resolved, error = _normalize_node(child, items)
            if error:
                return None, error
            children.append(resolved)
        return children, None
    if isinstance(value, Mapping):
        properties = raw_schema.get("properties") if isinstance(raw_schema, Mapping) else None
        result: dict[str, object] = {}
        for key, child in value.items():
            child_schema = properties.get(key) if isinstance(properties, Mapping) else None
            resolved, error = _normalize_node(child, child_schema)
            if error:
                return None, error
            result[str(key)] = resolved
        return result, None
    return value, None


def _schema_types(schema: Mapping[str, object]) -> set[str]:
    raw = schema.get("type")
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw if isinstance(item, str)}
    return set()


__all__ = [
    "MAX_RUNTIME_ITEMS", "normalize_runtime_limit_refs",
    "runtime_limit_template",
]
