"""Bounded deterministic Manifest construction shared by typed adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from ..discovery_input_bounds import runtime_limit_template
from ..input_plan import create_input_plan
from ..ports import DiscoveryMapping, DiscoveryRevision


def deterministic_input_plan(
    revision: DiscoveryRevision,
    *,
    input_keys: Sequence[str],
    identity_ref: str,
    list_handle_input_keys: Sequence[str] = (),
    list_url_input_keys: Sequence[str] = (),
    handle_input_keys: Sequence[str] = (),
    url_input_keys: Sequence[str] = (),
    max_items_input_keys: Sequence[str] = (),
) -> tuple[str | None, str | None]:
    """Build an input-only plan when public output fields are unavailable."""

    inputs = _properties(revision.input_schema)
    input_key = _first_input(
        inputs, input_keys, (*list_handle_input_keys, *list_url_input_keys)
    )
    if input_key is None:
        return None, "actorops_discovery_missing_target_input"
    max_items_key = _first_number(inputs, max_items_input_keys)
    max_items_value, max_items_error = _max_items_value(inputs, max_items_key)
    if max_items_error:
        return None, max_items_error
    template = {
        input_key: _input_value(
            input_key,
            identity_ref=identity_ref,
            list_handle_input_keys=list_handle_input_keys,
            list_url_input_keys=list_url_input_keys,
            handle_input_keys=handle_input_keys,
            url_input_keys=url_input_keys,
        ),
        **(
            {max_items_key: max_items_value}
            if max_items_key and max_items_key != input_key
            else {}
        ),
    }
    return create_input_plan(revision, template)


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
    handle_input_keys: Sequence[str] = (),
    url_input_keys: Sequence[str] = (),
    max_items_input_keys: Sequence[str] = (),
    identity_container_keys: Sequence[str] = (),
    avatar_pointer_keys: Sequence[str] = (),
    thumbnail_pointer_keys: Sequence[str] = (),
    identity_virtual_pointer: str | None = None,
    virtual_identity_field: str | None = None,
    virtual_identity_ref: str | None = None,
    identity_url_fallback: bool = False,
    native_id_url_fallback: bool = False,
) -> DiscoveryMapping:
    """Build only a schema-proven Manifest; ambiguous schemas stay pending."""

    inputs = _properties(revision.input_schema)
    outputs = _properties(revision.output_schema)
    list_inputs = (*list_handle_input_keys, *list_url_input_keys)
    input_key = _first_input(inputs, input_keys, list_inputs)
    max_items_key = _first_number(inputs, max_items_input_keys)
    max_items_value, max_items_error = _max_items_value(inputs, max_items_key)
    native_id = _first_scalar(outputs, (
        "id", "ID", "nativeId", "videoId", "Video ID", "tweetId",
        "postId", "shortCode", "shortcode", "native_id", "video_id",
        "tweet_id", "post_id", "short_code",
    ))
    url = _first_scalar(outputs, (
        "url", "URL", "canonicalUrl", "link", "permalink", "postUrl",
        "post_url", "tweetUrl", "tweet_url", "videoUrl", "video_url",
    ))
    if native_id is None and native_id_url_fallback:
        native_id = url
    published = _first_scalar(
        outputs, (
            "publishedAt", "publishedDate", "Published Time", "createdAt",
            "created_at", "timestamp", "date", "published_at",
            "publishDate", "publish_date", "published_date", "uploadDate",
            "upload_date", "takenAt", "taken_at", "caption_created_at",
        )
    )
    text = _first_scalar(outputs, (
        "text", "title", "Title", "description", "Description", "caption",
        "fullText", "full_text", "caption_text", "body", "content",
        "videoTitle", "video_title",
    ))
    identity_pointer = _identity_pointer(
        outputs, identity_pointer_keys, identity_container_keys
    )
    if identity_pointer is None and identity_url_fallback and url is not None:
        identity_pointer = f"/{url}"
    selected_identity_field = identity_field
    selected_identity_ref = identity_ref
    if identity_pointer is None and identity_virtual_pointer:
        identity_pointer = identity_virtual_pointer
        selected_identity_field = virtual_identity_field or identity_field
        selected_identity_ref = virtual_identity_ref or identity_ref
    avatar = _first_scalar(outputs, avatar_pointer_keys)
    thumbnail = _first_scalar(outputs, thumbnail_pointer_keys)
    if max_items_error:
        return DiscoveryMapping(None, max_items_error)
    if not all((input_key, native_id, url, published, text, identity_pointer)):
        return DiscoveryMapping(None, "actorops_discovery_mapping_unresolved")
    value = {
        "version": 1,
        "actor_id": revision.actor_id,
        "build_number": revision.build_number,
        "input": {
            input_key: _input_value(
                input_key,
                identity_ref=identity_ref,
                list_handle_input_keys=list_handle_input_keys,
                list_url_input_keys=list_url_input_keys,
                handle_input_keys=handle_input_keys,
                url_input_keys=url_input_keys,
            ),
            **(
                {max_items_key: max_items_value}
                if max_items_key and max_items_key != input_key
                else {}
            ),
        },
        "output": {
            "native_id": _output(native_id, "to_string"),
            "url": _output(url, "normalize_url"),
            "published_at": _output(published, "parse_datetime"),
            "text": _output(text, "to_string"),
            selected_identity_field: _pointer_output(identity_pointer, "to_string"),
            **(
                {"author_avatar_url": _output(avatar, "normalize_url")}
                if avatar
                else {}
            ),
            **(
                {"thumbnail_url": _output(thumbnail, "normalize_url")}
                if thumbnail
                else {}
            ),
        },
        "semantics": {
            "identity": {
                "output_field": selected_identity_field,
                "target_ref": selected_identity_ref,
                "match": _identity_match(selected_identity_ref),
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


def _first_scalar(
    values: Mapping[str, object], keys: Sequence[str]
) -> str | None:
    return next(
        (
            key for key in keys
            if key in values and not _schema_types(values[key]) & {"array", "object"}
        ),
        None,
    )


def _first_number(
    values: Mapping[str, object], keys: Sequence[str]
) -> str | None:
    for key in keys:
        if key not in values:
            continue
        types = _schema_types(values[key])
        if not types or types & {"integer", "number"}:
            return key
    return None


def _max_items_value(
    inputs: Mapping[str, object], key: str | None,
) -> tuple[object | None, str | None]:
    if key is None:
        return None, None
    return runtime_limit_template(inputs.get(key))


def _first_input(
    values: Mapping[str, object], keys: Sequence[str], list_keys: Sequence[str]
) -> str | None:
    for key in keys:
        if key not in values:
            continue
        types = _schema_types(values[key])
        if key in list_keys:
            if not types or "array" in types:
                return key
        elif not types or not types & {"array", "object"}:
            return key
    return None


def _identity_pointer(
    outputs: Mapping[str, object], keys: Sequence[str],
    container_keys: Sequence[str],
) -> str | None:
    container_seen = False
    for container in container_keys:
        definition = outputs.get(container)
        if definition is None or "object" not in _schema_types(definition):
            continue
        container_seen = True
        nested = _first_scalar(_properties(definition), keys)
        if nested:
            return f"/{container}/{nested}"
    if container_seen:
        return None
    top_level = _first_scalar(outputs, keys)
    return f"/{top_level}" if top_level else None


def _schema_types(value: object) -> frozenset[str]:
    if not isinstance(value, Mapping):
        return frozenset()
    raw = value.get("type")
    if isinstance(raw, str):
        return frozenset((raw,))
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return frozenset(item for item in raw if isinstance(item, str))
    return frozenset()


def _output(key: str, transform: str) -> dict[str, object]:
    return {"pointers": [f"/{key}"], "transforms": [transform]}


def _identity_match(reference: str) -> str:
    if reference.endswith("canonical_url"):
        return "url"
    if reference.endswith("native_id"):
        return "exact"
    return "handle"


def _pointer_output(pointer: str, transform: str) -> dict[str, object]:
    return {"pointers": [pointer], "transforms": [transform]}


def _input_value(
    key: str, *, identity_ref: str, list_handle_input_keys: Sequence[str],
    list_url_input_keys: Sequence[str], handle_input_keys: Sequence[str],
    url_input_keys: Sequence[str],
) -> object:
    if key in list_handle_input_keys:
        return [{"$ref": "target.handle"}]
    if key in list_url_input_keys:
        return [{"$ref": "target.canonical_url"}]
    if key in handle_input_keys:
        return {"$ref": "target.handle"}
    if key in url_input_keys:
        return {"$ref": "target.canonical_url"}
    return {"$ref": identity_ref}
