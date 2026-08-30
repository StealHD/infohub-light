"""Safe deterministic repairs for otherwise valid AI mapping proposals."""

from __future__ import annotations

import json
from collections.abc import Mapping

from .discovery_input_semantics import compatible_input_references
from .ports import DiscoveryMapping, DiscoveryRevision
from .youtube_capabilities import apply_youtube_input_capabilities


def repair_mapping_proposal(
    route_key: object,
    revision: DiscoveryRevision,
    mapping: DiscoveryMapping | None,
) -> DiscoveryMapping | None:
    """Repair only schema-provable reference and X identity omissions.

    The result still passes through the complete strict proof.  This function
    never creates a field path, literal, target value, or Dataset fact.
    """

    if mapping is None or not mapping.manifest_json:
        return mapping
    try:
        value = json.loads(mapping.manifest_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return mapping
    if not isinstance(value, dict):
        return mapping
    inputs = value.get("input")
    properties = revision.input_schema.get("properties")
    if isinstance(inputs, dict) and isinstance(properties, Mapping):
        value["input"] = {
            key: _repair_input(value, properties.get(key), key)
            for key, value in inputs.items()
        }
        if str(route_key) == "youtube/channel/items":
            value["input"] = apply_youtube_input_capabilities(
                value["input"], revision.input_schema
            )
    if str(route_key) == "x/profile/items":
        _repair_x_url_identity(value)
    return DiscoveryMapping(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        mapping.rejection_code,
    )


def _repair_input(value: object, schema: object, field: str) -> object:
    if not isinstance(schema, Mapping):
        return value
    if isinstance(value, Mapping) and set(value) == {"$ref"}:
        reference = value.get("$ref")
        compatible = compatible_input_references(field)
        if isinstance(reference, str) and reference not in compatible and len(compatible) == 1:
            return {"$ref": compatible[0]}
        return dict(value)
    if isinstance(value, list):
        item_schema = schema.get("items")
        return [
            _repair_input(item, item_schema, field)
            for item in value
        ]
    if isinstance(value, Mapping):
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            return dict(value)
        return {
            key: _repair_input(child, properties.get(key), str(key))
            for key, child in value.items()
        }
    return value


def _repair_x_url_identity(manifest: dict[str, object]) -> None:
    output = manifest.get("output")
    if not isinstance(output, dict) or "author_handle" in output:
        return
    url_mapping = output.get("url")
    if not isinstance(url_mapping, Mapping):
        return
    pointers = url_mapping.get("pointers")
    if not isinstance(pointers, list) or not pointers:
        return
    output["author_handle"] = dict(url_mapping)


__all__ = ["repair_mapping_proposal"]
