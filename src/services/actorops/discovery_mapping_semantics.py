"""Deterministic semantic proof for AI-proposed Actor field mappings."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .discovery_input_semantics import compatible_input_references
from .discovery_virtual_fields import (
    X_POST_URL_POINTER,
    YOUTUBE_TARGET_NATIVE_ID_POINTER,
    YOUTUBE_TARGET_URL_POINTER,
)


_IDENTITY_MEDIA_OR_URL = (
    "avatar", "banner", "image", "photo", "picture", "website",
)
_IDENTITY_EXACT_NEGATIVE = frozenset({
    "authorid", "bio", "description", "displayname", "id", "name",
    "text", "userid",
})
_IDENTITY_POSITIVE = (
    "author", "authorhandle", "authorusername", "handle", "ownerusername",
    "profilehandle", "screenname", "username", "userhandle",
)


def target_input_semantic_error(manifest: Mapping[str, object]) -> str | None:
    inputs = manifest.get("input")
    if not isinstance(inputs, Mapping):
        return "actorops_discovery_ai_missing_target_input"
    targets = [
        (str(field), reference)
        for field, value in inputs.items()
        for reference in _references(value)
        if reference.startswith("target.")
    ]
    if not targets or not any(
        _target_binding_matches(manifest, field, reference)
        for field, reference in targets
    ):
        return "actorops_discovery_ai_missing_target_input"
    return None


def output_semantic_error(manifest: Mapping[str, object]) -> str | None:
    outputs = manifest.get("output")
    if not isinstance(outputs, Mapping):
        return "actorops_discovery_ai_output_not_content_items"
    identity_field = _identity_field(manifest)
    host = _route_host(manifest)
    url_pointers = frozenset(_pointers(outputs.get("url")))
    for canonical in ("native_id", "url", "published_at"):
        pointers = _pointers(outputs.get(canonical))
        if not pointers or not all(
            _canonical_pointer_matches(canonical, pointer, host=host)
            or (
                canonical == "native_id"
                and pointer in url_pointers
                and _canonical_pointer_matches("url", pointer, host=host)
            )
            for pointer in pointers
        ):
            return (
                "actorops_discovery_ai_output_not_content_items"
                if canonical == "text"
                else "actorops_discovery_ai_ambiguous_output"
            )
    content_field = next(
        (name for name in ("title", "text") if _pointers(outputs.get(name))),
        None,
    )
    if content_field is None or not all(
        _canonical_pointer_matches("text", pointer, host=host)
        for pointer in _pointers(outputs.get(content_field))
    ):
        return "actorops_discovery_ai_output_not_content_items"
    identity_pointers = _pointers(outputs.get(identity_field))
    if not identity_pointers or not all(
        _identity_pointer_matches(
            pointer, identity_field, host=host, url_pointers=url_pointers
        )
        for pointer in identity_pointers
    ):
        return (
            "actorops_discovery_ai_missing_post_author_handle"
            if identity_field == "author_handle"
            else "actorops_discovery_ai_missing_identity"
        )
    return None


def _canonical_pointer_matches(canonical: str, pointer: str, *, host: str) -> bool:
    leaf = _normalized_leaf(pointer)
    if canonical == "native_id":
        return leaf == "id" or any(
            token in leaf for token in ("postid", "tweetid", "videoid", "shortcode")
        )
    if canonical == "url":
        if pointer == X_POST_URL_POINTER and host == "x.com":
            return True
        return leaf == "url" or any(
            token in leaf for token in ("link", "permalink", "posturl", "tweeturl", "videourl")
        )
    if canonical == "published_at":
        return any(
            token in leaf
            for token in ("created", "date", "publish", "taken", "time", "upload")
        )
    if canonical == "text":
        allowed = ("body", "content", "fulltext", "text", "title")
        if host == "instagram.com":
            allowed += ("caption",)
        elif host == "youtube.com":
            allowed += ("description", "title")
        return any(token in leaf for token in allowed)
    return False


def _identity_pointer_matches(
    pointer: str,
    identity_field: str,
    *,
    host: str,
    url_pointers: frozenset[str],
) -> bool:
    leaf = _normalized_leaf(pointer)
    if identity_field == "source_native_id":
        return pointer == YOUTUBE_TARGET_NATIVE_ID_POINTER or leaf == "id" or any(
            token in leaf for token in ("channelid", "sourceid", "userid")
        )
    if identity_field == "source_url":
        if pointer == YOUTUBE_TARGET_URL_POINTER and host == "youtube.com":
            return True
        return _canonical_pointer_matches("url", pointer, host="")
    if (
        identity_field == "author_handle"
        and host == "x.com"
        and pointer in url_pointers
        and _canonical_pointer_matches("url", pointer, host=host)
    ):
        return True
    if "url" in leaf or leaf in _IDENTITY_EXACT_NEGATIVE or any(
        token in leaf for token in _IDENTITY_MEDIA_OR_URL
    ):
        return leaf == "author"
    return any(token in leaf for token in _IDENTITY_POSITIVE)


def _target_field_matches(field: str, reference: str) -> bool:
    if _normalize(field) == "query":
        return False
    return reference in compatible_input_references(field)


def _target_binding_matches(
    manifest: Mapping[str, object], field: str, reference: str
) -> bool:
    if _target_field_matches(field, reference):
        return True
    inputs = manifest.get("input")
    return (
        reference == "target.handle"
        and _normalize(field) == "query"
        and _route_host(manifest) == "x.com"
        and isinstance(inputs, Mapping)
        and inputs.get("mode") == "Advanced Search"
        and inputs.get("query_type") == "Latest"
    )


def _references(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        if set(value) == {"$ref"} and isinstance(value.get("$ref"), str):
            return (str(value["$ref"]),)
        return tuple(
            reference for child in value.values() for reference in _references(child)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(reference for child in value for reference in _references(child))
    return ()


def _pointers(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    raw = value.get("pointers")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ()
    return tuple(str(pointer) for pointer in raw if isinstance(pointer, str))


def _identity_field(manifest: Mapping[str, object]) -> str:
    semantics = manifest.get("semantics")
    identity = semantics.get("identity") if isinstance(semantics, Mapping) else None
    value = identity.get("output_field") if isinstance(identity, Mapping) else None
    return str(value) if isinstance(value, str) and value else "author_handle"


def _route_host(manifest: Mapping[str, object]) -> str:
    semantics = manifest.get("semantics")
    raw = semantics.get("url_host_allowlist") if isinstance(semantics, Mapping) else None
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return str(raw[0]).casefold() if raw else ""
    return ""


def _normalized_leaf(pointer: str) -> str:
    return _normalize(pointer.rsplit("/", 1)[-1])


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


__all__ = ["output_semantic_error", "target_input_semantic_error"]
