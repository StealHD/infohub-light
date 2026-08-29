"""Build a value-free schema tree from one bounded, already-paid Dataset."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal


MAX_SCHEMA_DEPTH = 8
MAX_SCHEMA_FIELDS = 160
_SAFE_ENUM_FIELD = re.compile(
    r"(?:^|_)(?:type|kind|category|record_type|result_type|content_type|mode|status)$",
    re.IGNORECASE,
)
_SAFE_ENUM_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")


def observed_dataset_schema(
    rows: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Return types, shape and bounded safe enums without retaining row values."""

    budget = [MAX_SCHEMA_FIELDS]
    schemas = tuple(_schema(row, depth=0, field_name="", budget=budget) for row in rows)
    return _merge(schemas) if schemas else {"type": "object", "properties": {}}


def _schema(
    value: object, *, depth: int, field_name: str, budget: list[int]
) -> Mapping[str, object]:
    if depth >= MAX_SCHEMA_DEPTH or budget[0] <= 0:
        return {"type": _json_type(value)}
    if isinstance(value, Mapping):
        properties: dict[str, object] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            if budget[0] <= 0:
                break
            key = str(raw_key)
            if not key or len(key) > 128:
                continue
            budget[0] -= 1
            properties[key] = _schema(
                value[raw_key], depth=depth + 1, field_name=key, budget=budget
            )
        return {"type": "object", "properties": properties}
    if _sequence(value):
        samples = tuple(value[:20]) if isinstance(value, (list, tuple)) else tuple(value)[:20]
        items = tuple(
            _schema(item, depth=depth + 1, field_name=field_name, budget=budget)
            for item in samples
        )
        return {
            "type": "array",
            "minItemsObserved": len(value),
            "maxItemsObserved": len(value),
            "items": _merge(items) if items else {},
        }
    result: dict[str, object] = {"type": _json_type(value)}
    if _safe_enum(field_name, value):
        result["enum"] = [value]
    if isinstance(value, str):
        result["formatCategory"] = _format_category(value)
    return result


def _merge(schemas: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    if not schemas:
        return {}
    types = {str(schema.get("type")) for schema in schemas if schema.get("type")}
    if len(types) != 1:
        return {"anyOf": _unique(schemas)}
    kind = next(iter(types))
    if kind == "object":
        keys = sorted({
            str(key)
            for schema in schemas
            for key in (
                schema.get("properties", {}).keys()
                if isinstance(schema.get("properties"), Mapping)
                else ()
            )
        })
        properties: dict[str, object] = {}
        for key in keys:
            children = tuple(
                props[key]
                for schema in schemas
                if isinstance((props := schema.get("properties")), Mapping)
                and isinstance(props.get(key), Mapping)
            )
            properties[key] = _merge(children)
        return {"type": "object", "properties": properties}
    if kind == "array":
        items = tuple(
            item
            for schema in schemas
            if isinstance((item := schema.get("items")), Mapping) and item
        )
        lengths = tuple(
            int(schema.get("maxItemsObserved", 0)) for schema in schemas
        )
        return {
            "type": "array",
            "minItemsObserved": min(lengths, default=0),
            "maxItemsObserved": max(lengths, default=0),
            "items": _merge(items),
        }
    result: dict[str, object] = {"type": kind}
    enum = tuple(
        value
        for schema in schemas
        if isinstance(schema.get("enum"), list)
        for value in schema["enum"]
    )
    if enum and len(set(enum)) <= 8:
        result["enum"] = sorted(set(enum), key=str)
    formats = {
        str(schema["formatCategory"])
        for schema in schemas
        if schema.get("formatCategory")
    }
    if len(formats) == 1:
        result["formatCategory"] = next(iter(formats))
    return result


def _unique(schemas: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    for schema in schemas:
        if schema not in output:
            output.append(schema)
    return output[:8]


def _safe_enum(field_name: str, value: object) -> bool:
    if not _SAFE_ENUM_FIELD.search(field_name):
        return False
    return (
        isinstance(value, (bool, int))
        or isinstance(value, str) and bool(_SAFE_ENUM_VALUE.fullmatch(value))
    )


def _format_category(value: str) -> Literal["url", "datetime", "text"]:
    lowered = value.casefold()
    if lowered.startswith(("https://", "http://")):
        return "url"
    if "t" in value and (value.endswith("Z") or "+" in value[-7:]):
        return "datetime"
    return "text"


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, Mapping):
        return "object"
    if _sequence(value):
        return "array"
    return "string"


def _sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


__all__ = ["observed_dataset_schema"]
