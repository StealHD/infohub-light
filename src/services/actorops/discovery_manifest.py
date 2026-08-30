"""Prove AI-assisted Discovery Manifests against one exact public Schema."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from ..apify_actor_manifest import ActorManifestError, parse_actor_manifest
from ..apify_actor_row_extraction import (
    DatasetExtractionError,
    projected_output_schema,
)
from .discovery_input_semantics import input_reference_error
from .discovery_input_bounds import normalize_runtime_limit_refs
from .discovery_mapping_semantics import (
    output_semantic_error,
    target_input_semantic_error,
)
from .discovery_virtual_fields import virtual_output_pointer_allowed
from .ports import DiscoveryMapping, DiscoveryRevision


_REFERENCE_TYPES = {
    "target.canonical_url": "string",
    "target.native_id": "string",
    "target.handle": "string",
    "runtime.max_items": "integer",
    "runtime.since_iso": "string",
    "runtime.until_iso": "string",
}


def schema_proven_manifest(
    revision: DiscoveryRevision, mapping: DiscoveryMapping | None
) -> str | None:
    manifest_json, _error_code = validate_schema_proven_manifest(revision, mapping)
    return manifest_json


def validate_schema_proven_input(
    input_template: Mapping[str, object], schema: Mapping[str, object]
) -> str | None:
    """Return the safe proof error for one standalone InputPlan template."""

    return _input_error({"input": input_template}, schema)


def validate_schema_proven_manifest(
    revision: DiscoveryRevision, mapping: DiscoveryMapping | None
) -> tuple[str | None, str | None]:
    if mapping is None or not mapping.manifest_json:
        return None, "actorops_discovery_ai_mapping_missing"
    try:
        value = json.loads(mapping.manifest_json)
        if not isinstance(value, Mapping):
            raise TypeError("manifest must be an object")
        raw_input = value.get("input")
        if not isinstance(raw_input, Mapping):
            raise TypeError("manifest input must be an object")
        normalized_input, bounds_error = normalize_runtime_limit_refs(
            raw_input, revision.input_schema
        )
        if bounds_error:
            return None, bounds_error
        value = {**value, "input": normalized_input}
        manifest = parse_actor_manifest(value)
    except (ActorManifestError, TypeError, ValueError, json.JSONDecodeError):
        return None, "actorops_discovery_ai_manifest_invalid"
    if manifest.actor_id != revision.actor_id or manifest.build_number != revision.build_number:
        return None, "actorops_discovery_ai_revision_mismatch"
    if not isinstance(value, Mapping):
        return None, "actorops_discovery_ai_manifest_invalid"
    input_error = _input_error(value, revision.input_schema)
    if input_error is not None:
        return None, input_error
    output_error = _output_error(value, revision.output_schema)
    if output_error is not None:
        return None, output_error
    semantic_error = output_semantic_error(value)
    if semantic_error is not None:
        return None, semantic_error
    target_error = target_input_semantic_error(value)
    if target_error is not None:
        return None, target_error
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        None,
    )


def _input_proven(manifest: Mapping[str, object], schema: Mapping[str, object]) -> bool:
    return _input_error(manifest, schema) is None


def _input_error(
    manifest: Mapping[str, object], schema: Mapping[str, object]
) -> str | None:
    inputs = manifest.get("input")
    properties = schema.get("properties")
    if not isinstance(inputs, Mapping) or not isinstance(properties, Mapping):
        return "actorops_discovery_ai_input_schema_invalid"
    required = _required(schema)
    if not required.issubset(str(key) for key in inputs):
        return "actorops_discovery_ai_missing_required_input_value"
    for key, value in inputs.items():
        if not isinstance(key, str) or key not in properties:
            return "actorops_discovery_ai_input_field_unknown"
        if not _value_proven(value, properties[key]):
            return "actorops_discovery_ai_input_value_invalid"
        reference_error = input_reference_error(key, value, required=key in required)
        if reference_error is not None:
            return reference_error
    return None


def _value_proven(value: object, raw_schema: object) -> bool:
    if not isinstance(raw_schema, Mapping):
        return False
    alternatives = _alternatives(raw_schema)
    if alternatives:
        return any(_value_proven(value, option) for option in alternatives)
    combined = raw_schema.get("allOf")
    if isinstance(combined, Sequence) and not isinstance(combined, (str, bytes)):
        return all(_value_proven(value, option) for option in combined)
    reference = _reference(value)
    types = _types(raw_schema)
    if reference is not None:
        if "const" in raw_schema or isinstance(raw_schema.get("enum"), list):
            return False
        return _type_compatible(_REFERENCE_TYPES[reference], types)
    if not _literal_allowed(value, raw_schema):
        return False
    if not _type_compatible(_json_type(value), types):
        return False
    if isinstance(value, Mapping):
        properties = raw_schema.get("properties")
        if not isinstance(properties, Mapping):
            return raw_schema.get("additionalProperties") is not False
        if not _required(raw_schema).issubset(str(key) for key in value):
            return False
        return all(
            isinstance(key, str)
            and key in properties
            and _value_proven(child, properties[key])
            for key, child in value.items()
        )
    if isinstance(value, list):
        items = raw_schema.get("items")
        if items is None:
            return True
        return isinstance(items, Mapping) and all(
            _value_proven(child, items) for child in value
        )
    return True


def _output_proven(manifest: Mapping[str, object], schema: Mapping[str, object]) -> bool:
    return _output_error(manifest, schema) is None


def _output_error(
    manifest: Mapping[str, object], schema: Mapping[str, object]
) -> str | None:
    output = manifest.get("output")
    if not isinstance(output, Mapping) or not isinstance(schema.get("properties"), Mapping):
        return "actorops_discovery_ai_output_schema_invalid"
    try:
        parsed = parse_actor_manifest(manifest)
        schema = projected_output_schema(schema, parsed.row_extraction)
    except (ActorManifestError, DatasetExtractionError, TypeError, ValueError):
        return "actorops_discovery_ai_nested_extraction_failed"
    if parsed.row_extraction is not None:
        for row_filter in parsed.row_extraction.filters:
            resolved = _pointer_schema(schema, row_filter.pointer)
            if resolved is None or not _filter_values_proven(
                resolved, row_filter.allowed_values
            ):
                return "actorops_discovery_ai_mixed_rows_unclassified"
    if not {"native_id", "url", "published_at"}.issubset(output):
        return "actorops_discovery_ai_required_output_missing"
    for canonical, value in output.items():
        if not isinstance(value, Mapping) or not isinstance(value.get("pointers"), list):
            return "actorops_discovery_ai_output_mapping_invalid"
        transforms = value.get("transforms")
        transforms = transforms if isinstance(transforms, list) else []
        for pointer in value["pointers"]:
            if not isinstance(pointer, str):
                return "actorops_discovery_ai_output_pointer_invalid"
            if virtual_output_pointer_allowed(manifest, str(canonical), pointer):
                continue
            resolved = _pointer_schema(schema, pointer)
            if resolved is None:
                return "actorops_discovery_ai_output_pointer_unknown"
            if not _output_type_proven(resolved, transforms):
                return "actorops_discovery_ai_output_pointer_nonscalar"
    return None


def _pointer_schema(schema: Mapping[str, object], pointer: str) -> Mapping[str, object] | None:
    if not pointer.startswith("/") or pointer == "/":
        return None
    nodes: tuple[Mapping[str, object], ...] = (schema,)
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        next_nodes: list[Mapping[str, object]] = []
        for node in nodes:
            for option in _alternatives(node) or (node,):
                properties = option.get("properties")
                child = properties.get(part) if isinstance(properties, Mapping) else None
                if isinstance(child, Mapping):
                    next_nodes.append(child)
        if not next_nodes:
            return None
        nodes = tuple(next_nodes)
    return nodes[0] if nodes else None


def _output_type_proven(schema: Mapping[str, object], transforms: Sequence[object]) -> bool:
    types = _types(schema)
    if not types:
        return True
    if types & {"array", "object"}:
        return False
    if "normalize_url" in transforms or "parse_datetime" in transforms or "strip_html" in transforms:
        return bool(types & {"string", "integer", "number"})
    return True


def _filter_values_proven(
    schema: Mapping[str, object], values: Sequence[object]
) -> bool:
    options = schema.get("enum")
    if isinstance(options, list):
        return all(value in options for value in values)
    if "const" in schema:
        return all(value == schema.get("const") for value in values)
    return False


def _alternatives(schema: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    for key in ("oneOf", "anyOf"):
        raw = schema.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            return tuple(item for item in raw if isinstance(item, Mapping))
    return ()


def _required(schema: Mapping[str, object]) -> set[str]:
    raw = schema.get("required")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {str(item) for item in raw if isinstance(item, str)}


def _types(schema: Mapping[str, object]) -> set[str]:
    raw = schema.get("type")
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return {str(item) for item in raw if isinstance(item, str)}
    if isinstance(schema.get("properties"), Mapping):
        return {"object"}
    if isinstance(schema.get("items"), Mapping):
        return {"array"}
    return set()


def _reference(value: object) -> str | None:
    if not isinstance(value, Mapping) or set(value) != {"$ref"}:
        return None
    reference = value.get("$ref")
    return str(reference) if reference in _REFERENCE_TYPES else None


def _literal_allowed(value: object, schema: Mapping[str, object]) -> bool:
    if isinstance(value, (Mapping, list)):
        return True
    if "const" in schema and value != schema.get("const"):
        return False
    enum = schema.get("enum")
    if isinstance(enum, list):
        return value in enum
    if "default" in schema:
        return value == schema.get("default")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool):
            return False
        if float(value) < float(minimum):
            return False
        if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
            if float(value) > float(maximum):
                return False
        return 1 <= float(value) <= 100
    return False


def _json_type(value: object) -> str:
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
    if isinstance(value, list):
        return "array"
    return "object"


def _type_compatible(actual: str, expected: set[str]) -> bool:
    return not expected or actual in expected or (actual == "integer" and "number" in expected)


__all__ = ["schema_proven_manifest", "validate_schema_proven_manifest"]
