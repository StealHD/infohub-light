"""Bounded, value-free response structure summaries for Job diagnostics."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Iterable


DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_FIELDS = 256
DEFAULT_MAX_BYTES = 8 * 1024
DEFAULT_MAX_JOB_BYTES = 64 * 1024
_SAFE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,79}$")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "string"


def _safe_key(value: Any) -> str:
    key = str(value)
    return key if _SAFE_KEY_RE.fullmatch(key) else "[dynamic-key]"


def _merge_type(current: str | None, candidate: str) -> str:
    if current is None or current == candidate:
        return candidate
    return "mixed"


def _bounded_result(
    *,
    root_type: str,
    field_types: dict[str, str],
    truncated: bool,
    max_bytes: int,
) -> dict[str, Any]:
    fields = [
        {"path": path, "type": field_types[path]}
        for path in sorted(field_types)
    ]
    result = {
        "root_type": root_type,
        "fields": fields,
        "truncated": bool(truncated),
    }
    while fields and len(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ) > max_bytes:
        fields.pop()
        result["truncated"] = True
    if len(json.dumps(result, separators=(",", ":")).encode("utf-8")) > max_bytes:
        return {"root_type": root_type, "fields": [], "truncated": True}
    return result


def extract_response_schema(
    value: Any,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_fields: int = DEFAULT_MAX_FIELDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Return stable field paths and types without retaining any field value."""

    field_types: dict[str, str] = {}
    truncated = False

    def add(path: str, value_type: str) -> None:
        nonlocal truncated
        if path not in field_types and len(field_types) >= max(0, int(max_fields)):
            truncated = True
            return
        field_types[path] = _merge_type(field_types.get(path), value_type)

    def visit_children(candidate: Any, prefix: str, depth: int) -> None:
        nonlocal truncated
        if depth >= max(0, int(max_depth)):
            if isinstance(candidate, dict) and candidate:
                truncated = True
            elif isinstance(candidate, (list, tuple)) and candidate:
                truncated = True
            return
        if isinstance(candidate, dict):
            for raw_key, child in candidate.items():
                key = _safe_key(raw_key)
                path = f"{prefix}.{key}" if prefix else key
                child_type = _value_type(child)
                add(path, child_type)
                if child_type in {"object", "array"}:
                    visit_children(child, path, depth + 1)
        elif isinstance(candidate, (list, tuple)):
            for child in candidate:
                if isinstance(child, (dict, list, tuple)):
                    visit_children(child, prefix, depth + 1)

    root_type = _value_type(value)
    visit_children(value, "", 0)
    return _bounded_result(
        root_type=root_type,
        field_types=field_types,
        truncated=truncated,
        max_bytes=max(128, int(max_bytes)),
    )


def merge_response_schemas(
    schemas: Iterable[dict[str, Any]],
    *,
    max_fields: int = DEFAULT_MAX_FIELDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Merge already value-free schemas without accessing upstream payloads."""

    root_type: str | None = None
    field_types: dict[str, str] = {}
    truncated = False
    for schema in schemas:
        candidate_root = str(schema.get("root_type") or "null")
        root_type = _merge_type(root_type, candidate_root)
        truncated = truncated or bool(schema.get("truncated"))
        for field in schema.get("fields") or []:
            if not isinstance(field, dict):
                continue
            path = str(field.get("path") or "")
            field_type = str(field.get("type") or "mixed")
            if not path:
                continue
            if path not in field_types and len(field_types) >= max(0, int(max_fields)):
                truncated = True
                continue
            field_types[path] = _merge_type(field_types.get(path), field_type)
    return _bounded_result(
        root_type=root_type or "null",
        field_types=field_types,
        truncated=truncated,
        max_bytes=max(128, int(max_bytes)),
    )


def bound_source_response_schemas(
    records: Iterable[dict[str, Any]],
    *,
    max_bytes: int = DEFAULT_MAX_JOB_BYTES,
) -> list[dict[str, Any]]:
    """Bound the combined source schema projection stored in one Job result."""

    bounded = [deepcopy(record) for record in records if isinstance(record, dict)]
    limit = max(2, int(max_bytes))
    while bounded and len(
        json.dumps(bounded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ) > limit:
        bounded.pop()
        if bounded:
            bounded[-1]["job_truncated"] = True
    return bounded
