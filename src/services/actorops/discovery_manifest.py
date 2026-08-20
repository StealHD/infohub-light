"""Validate AI-assisted Discovery Manifests against the exact public Schema."""

from __future__ import annotations

import json
from collections.abc import Mapping

from ..apify_actor_manifest import ActorManifestError, parse_actor_manifest
from .ports import DiscoveryMapping, DiscoveryRevision


def schema_proven_manifest(
    revision: DiscoveryRevision, mapping: DiscoveryMapping | None
) -> str | None:
    if mapping is None or not mapping.manifest_json:
        return None
    try:
        value = json.loads(mapping.manifest_json)
        manifest = parse_actor_manifest(value)
    except (ActorManifestError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if manifest.actor_id != revision.actor_id or manifest.build_number != revision.build_number:
        return None
    if not isinstance(value, Mapping) or not _input_proven(value, revision.input_schema):
        return None
    if not _output_proven(value, revision.output_schema):
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _input_proven(manifest: Mapping[str, object], schema: Mapping[str, object]) -> bool:
    inputs = manifest.get("input")
    properties = schema.get("properties")
    return isinstance(inputs, Mapping) and isinstance(properties, Mapping) and all(
        str(key) in properties for key in inputs
    )


def _output_proven(manifest: Mapping[str, object], schema: Mapping[str, object]) -> bool:
    output = manifest.get("output")
    properties = schema.get("properties")
    if not isinstance(output, Mapping) or not isinstance(properties, Mapping):
        return False
    required = {"native_id", "url", "published_at"}
    if not required.issubset(output):
        return False
    for value in output.values():
        if not isinstance(value, Mapping) or not isinstance(value.get("pointers"), list):
            return False
        for pointer in value["pointers"]:
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                return False
            key = pointer[1:].split("/", 1)[0].replace("~1", "/").replace("~0", "~")
            if key not in properties:
                return False
    return True


__all__ = ["schema_proven_manifest"]
