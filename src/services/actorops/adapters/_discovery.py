"""Bounded deterministic Manifest construction shared by typed adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from ..ports import DiscoveryMapping, DiscoveryRevision


def deterministic_manifest(
    revision: DiscoveryRevision,
    *,
    input_keys: Sequence[str],
    identity_field: str,
    identity_pointer_keys: Sequence[str],
    identity_ref: str,
    allowed_host: str,
    list_handle_input_keys: Sequence[str] = (),
    list_url_input_keys: Sequence[str] = (),
) -> DiscoveryMapping:
    """Build only a schema-proven Manifest; ambiguous schemas stay pending."""

    inputs = _properties(revision.input_schema)
    outputs = _properties(revision.output_schema)
    input_key = _first(inputs, input_keys)
    native_id = _first(outputs, ("id", "nativeId", "videoId", "tweetId", "postId", "shortCode", "shortcode"))
    url = _first(outputs, ("url", "canonicalUrl", "link"))
    published = _first(outputs, ("publishedAt", "createdAt", "timestamp"))
    text = _first(outputs, ("text", "title", "description", "caption"))
    identity = _first(outputs, identity_pointer_keys)
    if not all((input_key, native_id, url, published, text, identity)):
        return DiscoveryMapping(None, "actorops_discovery_mapping_unresolved")
    value = {
        "version": 1,
        "actor_id": revision.actor_id,
        "build_number": revision.build_number,
        "input": {input_key: _input_value(
            input_key, identity_ref=identity_ref,
            list_handle_input_keys=list_handle_input_keys,
            list_url_input_keys=list_url_input_keys,
        )},
        "output": {
            "native_id": _output(native_id, "to_string"),
            "url": _output(url, "normalize_url"),
            "published_at": _output(published, "parse_datetime"),
            "text": _output(text, "to_string"),
            identity_field: _output(identity, "to_string"),
        },
        "semantics": {
            "identity": {
                "output_field": identity_field,
                "target_ref": identity_ref,
                "match": "exact" if identity_ref.endswith("native_id") else "handle",
            },
            "url_host_allowlist": [allowed_host],
        },
    }
    return DiscoveryMapping(json.dumps(value, ensure_ascii=False, sort_keys=True))


def manifest_hash(manifest_json: str) -> str:
    return hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()


def _properties(schema: Mapping[str, object]) -> Mapping[str, object]:
    raw = schema.get("properties")
    return raw if isinstance(raw, Mapping) else {}


def _first(values: Mapping[str, object], keys: Sequence[str]) -> str | None:
    return next((key for key in keys if key in values), None)


def _output(key: str, transform: str) -> dict[str, object]:
    return {"pointers": [f"/{key}"], "transforms": [transform]}


def _input_value(
    key: str, *, identity_ref: str, list_handle_input_keys: Sequence[str],
    list_url_input_keys: Sequence[str],
) -> object:
    if key in list_handle_input_keys:
        return [{"$ref": "target.handle"}]
    if key in list_url_input_keys:
        return [{"$ref": "target.canonical_url"}]
    return {"$ref": identity_ref}
