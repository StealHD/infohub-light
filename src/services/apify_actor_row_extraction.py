"""Bounded, declarative extraction of publication rows from Actor Datasets."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_EXTRACTION_POINTERS = 6
MAX_EXTRACTION_DEPTH = 8
MAX_EXTRACTION_WILDCARDS = 2
MAX_EXTRACTION_FILTERS = 4
MAX_EXTRACTED_ROWS = 100
_SAFE_LITERAL = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")


class RowFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    pointer: str
    allowed_values: tuple[str | int | bool, ...] = Field(
        min_length=1, max_length=8
    )

    @field_validator("pointer")
    @classmethod
    def _safe_pointer(cls, value: str) -> str:
        return validate_extraction_pointer(value, allow_wildcard=False)

    @field_validator("allowed_values")
    @classmethod
    def _safe_values(
        cls, values: tuple[str | int | bool, ...]
    ) -> tuple[str | int | bool, ...]:
        for value in values:
            if isinstance(value, str) and not _SAFE_LITERAL.fullmatch(value):
                raise ValueError("row filter contains an unsafe string literal")
        if len(set(values)) != len(values):
            raise ValueError("row filter values must be unique")
        return values


class RowExtractionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    mode: Literal["top_level", "nested_array"] = "top_level"
    pointers: tuple[str, ...] = Field(
        default=(), max_length=MAX_EXTRACTION_POINTERS
    )
    filters: tuple[RowFilter, ...] = Field(
        default=(), max_length=MAX_EXTRACTION_FILTERS
    )

    @field_validator("pointers")
    @classmethod
    def _safe_pointers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(validate_extraction_pointer(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("row extraction pointers must be unique")
        return normalized

    @model_validator(mode="after")
    def _mode_shape(self) -> RowExtractionPlan:
        if self.mode == "top_level" and self.pointers:
            raise ValueError("top-level extraction must not declare pointers")
        if self.mode == "nested_array" and not self.pointers:
            raise ValueError("nested extraction requires at least one pointer")
        return self


class DatasetExtractionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExtractedRows:
    rows: tuple[Mapping[str, object], ...]
    shape: Literal["flat", "nested", "mixed"]


def extract_dataset_rows(
    rows: Sequence[Mapping[str, object]],
    plan: RowExtractionPlan | None,
    *,
    limit: int = MAX_EXTRACTED_ROWS,
) -> ExtractedRows:
    selected = plan or RowExtractionPlan()
    bounded_limit = min(max(int(limit), 1), MAX_EXTRACTED_ROWS)
    if selected.mode == "top_level":
        return _filter_rows(tuple(rows), selected.filters, bounded_limit, "flat")
    output: list[Mapping[str, object]] = []
    located = False
    empty_array = False
    skipped = False
    for root in rows:
        matches: list[tuple[object, Mapping[str, object] | None]] = []
        for pointer in selected.pointers:
            matches = _resolve_matches(root, pointer)
            if matches:
                break
        if not matches:
            continue
        located = True
        for value, parent in matches:
            if not _sequence(value):
                raise DatasetExtractionError("apify_actor_nested_extraction_failed")
            if not value:
                empty_array = True
            for item in value:
                if not isinstance(item, Mapping):
                    raise DatasetExtractionError(
                        "apify_actor_nested_extraction_failed"
                    )
                envelope: Mapping[str, object] = {
                    "item": dict(item),
                    "parent": dict(parent or root),
                    "root": dict(root),
                }
                if not _matches_filters(envelope, selected.filters):
                    skipped = True
                    if _publication_like(envelope):
                        raise DatasetExtractionError(
                            "apify_actor_mixed_rows_unclassified"
                        )
                    continue
                output.append(envelope)
                if len(output) > bounded_limit:
                    raise DatasetExtractionError(
                        "apify_actor_dataset_expansion_overflow"
                    )
    if not located and rows:
        raise DatasetExtractionError("apify_actor_nested_extraction_failed")
    if not output and located and not empty_array and rows:
        raise DatasetExtractionError("apify_actor_mixed_rows_unclassified")
    return ExtractedRows(tuple(output), "mixed" if skipped else "nested")


def projected_output_schema(
    schema: Mapping[str, object], plan: RowExtractionPlan | None
) -> Mapping[str, object]:
    if plan is None or plan.mode == "top_level":
        return schema
    item_schemas: list[Mapping[str, object]] = []
    parent_schemas: list[Mapping[str, object]] = []
    for pointer in plan.pointers:
        resolved = _resolve_schema(schema, pointer)
        if resolved is not None:
            item_schema, parent_schema = resolved
            item_schemas.append(item_schema)
            parent_schemas.append(parent_schema)
    if not item_schemas:
        raise DatasetExtractionError("apify_actor_nested_extraction_failed")
    return {
        "type": "object",
        "properties": {
            "item": _combine_schemas(item_schemas),
            "parent": _combine_schemas(parent_schemas),
            "root": dict(schema),
        },
    }


def validate_extraction_pointer(
    value: str, *, allow_wildcard: bool = True
) -> str:
    pointer = str(value or "").strip()
    if not pointer.startswith("/") or pointer == "/" or len(pointer) > 512:
        raise ValueError("row extraction pointer is invalid")
    parts = pointer[1:].split("/")
    if len(parts) > MAX_EXTRACTION_DEPTH:
        raise ValueError("row extraction pointer is too deep")
    wildcards = sum(part == "*" for part in parts)
    if wildcards > MAX_EXTRACTION_WILDCARDS or (wildcards and not allow_wildcard):
        raise ValueError("row extraction wildcard is invalid")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or (part != "*" and re.search(r"~(?![01])", part))
        ):
            raise ValueError("row extraction pointer segment is invalid")
    return pointer


def _filter_rows(
    rows: tuple[Mapping[str, object], ...], filters: tuple[RowFilter, ...],
    limit: int, base_shape: Literal["flat", "nested"],
) -> ExtractedRows:
    output: list[Mapping[str, object]] = []
    skipped = False
    for row in rows:
        if not _matches_filters(row, filters):
            skipped = True
            if _publication_like(row):
                raise DatasetExtractionError("apify_actor_mixed_rows_unclassified")
            continue
        output.append(row)
        if len(output) > limit:
            raise DatasetExtractionError("apify_actor_dataset_expansion_overflow")
    return ExtractedRows(tuple(output), "mixed" if skipped else base_shape)


def _resolve_matches(
    root: Mapping[str, object], pointer: str
) -> list[tuple[object, Mapping[str, object] | None]]:
    nodes: list[tuple[object, Mapping[str, object] | None]] = [(root, None)]
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        next_nodes: list[tuple[object, Mapping[str, object] | None]] = []
        for node, _parent in nodes:
            if part == "*" and _sequence(node):
                next_nodes.extend(
                    (child, child if isinstance(child, Mapping) else None)
                    for child in node
                )
            elif isinstance(node, Mapping) and part in node:
                next_nodes.append((node[part], node))
        nodes = next_nodes
        if not nodes:
            break
    return nodes


def _resolve_schema(
    root: Mapping[str, object], pointer: str
) -> tuple[Mapping[str, object], Mapping[str, object]] | None:
    nodes: list[tuple[Mapping[str, object], Mapping[str, object]]] = [(root, root)]
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        next_nodes: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
        for node, parent in nodes:
            if part == "*":
                item = node.get("items")
                if isinstance(item, Mapping):
                    next_nodes.append((item, item))
                continue
            properties = node.get("properties")
            child = properties.get(part) if isinstance(properties, Mapping) else None
            if isinstance(child, Mapping):
                next_nodes.append((child, node))
        nodes = next_nodes
        if not nodes:
            return None
    for node, parent in nodes:
        item = node.get("items")
        if isinstance(item, Mapping):
            return item, parent
    return None


def _matches_filters(row: Mapping[str, object], filters: tuple[RowFilter, ...]) -> bool:
    return all(_resolve_scalar(row, rule.pointer) in rule.allowed_values for rule in filters)


def _resolve_scalar(row: Mapping[str, object], pointer: str) -> object:
    node: object = row
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _publication_like(value: object, *, depth: int = 0) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = {
        re.sub(r"[^a-z0-9]", "", str(key).casefold())
        for key in value
    }
    has_time = any(
        token in key for key in keys
        for token in ("created", "published", "timestamp", "date")
    )
    has_content = any(
        token in key for key in keys
        for token in ("id", "url", "text", "title", "caption")
    )
    if has_time and has_content:
        return True
    if depth >= 2:
        return False
    return any(
        _publication_like(child, depth=depth + 1)
        for key, child in value.items()
        if str(key) in {"item", "parent", "root"}
    )


def _combine_schemas(values: list[Mapping[str, object]]) -> Mapping[str, object]:
    return dict(values[0]) if len(values) == 1 else {"anyOf": [dict(v) for v in values]}


def _sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


__all__ = [
    "DatasetExtractionError",
    "ExtractedRows",
    "MAX_EXTRACTED_ROWS",
    "RowExtractionPlan",
    "extract_dataset_rows",
    "projected_output_schema",
    "validate_extraction_pointer",
]
