"""Explicit YouTube channel-item Build input mapping.

The Store's ``startUrls`` convention is not portable across Actor platforms:
many YouTube Actors declare it as an Apify ``stringList`` while X actors use
objects with a nested ``url`` field.  Keep that platform contract here rather
than letting generic discovery guess a dialect from a field name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


_URL_LIST_FIELDS = frozenset({"starturls", "channelurls", "urls"})
_URL_FIELDS = frozenset({"url", "channelurl"})
_CHANNEL_ID_LIST_FIELDS = frozenset({"channelids"})
_CHANNEL_ID_FIELDS = frozenset({"channelid"})
_COUNT_FIELDS = (
    "maxitems",
    "maxresults",
    "maxvideos",
    "maxvideosperchannel",
    "limit",
)


def youtube_channel_items_input_template(
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the one safe input template for ``youtube/channel/items``.

    Only explicitly declared channel URL/ID inputs are accepted.  Array fields
    must be a string list (or an Apify ``stringList`` editor); object-form
    ``startUrls`` is deliberately rejected because it belongs to a different
    platform dialect.  Optional controls are set only when their Build Schema
    proves a value that suppresses channel metadata in favour of videos.
    """

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    required = _required_names(schema)
    if required is None:
        return {}

    target = _target_field(properties)
    if target is None:
        return {}
    name, value = target
    template: dict[str, Any] = {name: value}

    for count_name in _COUNT_FIELDS:
        for raw_name, raw_schema in properties.items():
            if (
                isinstance(raw_name, str)
                and _normalize(raw_name) == count_name
                and _numeric(raw_schema)
            ):
                template[raw_name] = {"$ref": "runtime.max_items"}
                break
        else:
            continue
        break

    for raw_name, raw_schema in properties.items():
        if not isinstance(raw_name, str) or not isinstance(
            raw_schema, Mapping
        ):
            continue
        normalized = _normalize(raw_name)
        if normalized == "fetchchannelinfo" and _boolean(raw_schema):
            template[raw_name] = False
        elif normalized == "channelcontent":
            videos = _enum_value(raw_schema, "videos")
            if videos is not None:
                template[raw_name] = videos
        elif normalized == "includeshorts" and _boolean(raw_schema):
            template[raw_name] = False

    for name in required:
        if name in template:
            continue
        raw_schema = properties.get(name)
        literal = _required_literal(raw_schema)
        if literal is _MISSING:
            return {}
        template[name] = literal
    return template


def input_template_for_registered_route(
    platform: str,
    target_type: str,
    capability: str,
    schema: Mapping[str, Any],
    generic_template: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch the public Build input through an explicit Route binding."""

    identity = (platform, target_type, capability)
    if identity == ("youtube", "channel", "items"):
        return youtube_channel_items_input_template(schema)
    if identity in {
        ("x", "profile", "items"),
        ("instagram", "profile", "items"),
    }:
        return generic_template(schema)
    return {}


def _target_field(properties: Mapping[Any, Any]) -> tuple[str, Any] | None:
    for names, reference in (
        (_CHANNEL_ID_LIST_FIELDS, "target.native_id"),
        (_CHANNEL_ID_FIELDS, "target.native_id"),
        (_URL_LIST_FIELDS, "target.canonical_url"),
        (_URL_FIELDS, "target.canonical_url"),
    ):
        for raw_name, raw_schema in properties.items():
            if not isinstance(raw_name, str) or not isinstance(
                raw_schema, Mapping
            ):
                continue
            if _normalize(raw_name) not in names:
                continue
            if names in {_CHANNEL_ID_LIST_FIELDS, _URL_LIST_FIELDS}:
                if _string_list(raw_schema):
                    return raw_name, [{"$ref": reference}]
            elif _string(raw_schema):
                return raw_name, {"$ref": reference}
    return None


def _required_names(schema: Mapping[str, Any]) -> tuple[str, ...] | None:
    raw = schema.get("required", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        return ()
    names: list[str] = []
    for value in raw:
        if (
            not isinstance(value, str)
            or not value
            or _normalize(value)
            != value.casefold().replace("_", "").replace("-", "")
        ):
            return None
        names.append(value)
    return tuple(names)


_MISSING = object()


def _required_literal(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return _MISSING
    for key in ("const", "default"):
        literal = value.get(key, _MISSING)
        if _safe_literal(literal):
            return literal
    enum = value.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes, bytearray)):
        for literal in enum:
            if _safe_literal(literal):
                return literal
    if _boolean(value):
        return False
    if _numeric(value):
        return {"$ref": "runtime.max_items"}
    return _MISSING


def _safe_literal(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _enum_value(schema: Mapping[str, Any], expected: str) -> str | None:
    values = schema.get("enum")
    if not isinstance(values, Sequence) or isinstance(
        values, (str, bytes, bytearray)
    ):
        return None
    for value in values:
        if isinstance(value, str) and value.casefold() == expected:
            return value
    return None


def _string_list(schema: Mapping[str, Any]) -> bool:
    if str(schema.get("type") or "").casefold() != "array":
        return False
    if str(schema.get("editor") or "").casefold() == "stringlist":
        return True
    items = schema.get("items")
    return isinstance(items, Mapping) and _string(items)


def _string(schema: Mapping[str, Any]) -> bool:
    return str(schema.get("type") or "").casefold() == "string"


def _numeric(value: Any) -> bool:
    return isinstance(value, Mapping) and str(
        value.get("type") or ""
    ).casefold() in {"integer", "number"}


def _boolean(value: Any) -> bool:
    return isinstance(value, Mapping) and str(
        value.get("type") or ""
    ).casefold() == "boolean"


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


__all__ = [
    "input_template_for_registered_route",
    "youtube_channel_items_input_template",
]
