"""Semantic proof for symbolic values in Actor input templates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


_KNOWN_REFERENCES = (
    "target.canonical_url",
    "target.native_id",
    "target.handle",
    "runtime.max_items",
    "runtime.since_iso",
    "runtime.until_iso",
)


def input_reference_error(field: str, value: object, *, required: bool) -> str | None:
    """Reject type-compatible references placed in semantically unrelated fields."""

    references = _references(value)
    if all(_reference_matches(field, reference) for reference in references):
        return None
    return (
        "actorops_discovery_ai_missing_required_input_value"
        if required
        else "actorops_discovery_ai_input_value_invalid"
    )


def compatible_input_references(field: str) -> tuple[str, ...]:
    """Return the exhaustive symbolic references allowed by field semantics."""

    return tuple(
        reference for reference in _KNOWN_REFERENCES
        if _reference_matches(field, reference)
    )


def _reference_matches(field: str, reference: str) -> bool:
    tokens, normalized = _field_parts(field)
    is_limit = bool(
        tokens & {"count", "items", "limit", "max", "number", "results"}
        or (
            "per" in tokens
            and bool(tokens & {"comments", "posts", "profiles", "videos"})
        )
    )
    if reference == "target.canonical_url":
        return bool(
            tokens & {"url", "urls", "uri", "uris"}
            or normalized in {
                "channel", "channels", "channelinput", "channelinputs",
                "start", "target", "targets",
            }
        )
    if reference == "target.native_id":
        return bool(
            tokens & {"id", "ids"}
            or normalized in {
                "channel", "channels", "channelinput", "channelinputs",
            }
        )
    if reference == "target.handle":
        return not is_limit and not bool(
            tokens & {"url", "urls", "uri", "uris"}
        ) and bool(
            tokens & {
                "author", "authors", "from", "handle", "handles",
                "profile", "profiles", "query", "screenname", "username",
                "usernames",
            }
            or normalized in {"channel", "channels", "channelinput", "channelinputs"}
        )
    if reference == "runtime.max_items":
        return is_limit
    if reference == "runtime.since_iso":
        return bool(tokens & {"after", "from", "newer", "since", "start"})
    if reference == "runtime.until_iso":
        return bool(tokens & {"before", "end", "older", "until"})
    return False


def _field_parts(field: str) -> tuple[set[str], str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    tokens = {
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+", separated)
        if token
    }
    return tokens, re.sub(r"[^a-z0-9]", "", field.casefold())


def _references(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        if set(value) == {"$ref"} and isinstance(value.get("$ref"), str):
            return (str(value["$ref"]),)
        return tuple(reference for child in value.values() for reference in _references(child))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(reference for child in value for reference in _references(child))
    return ()


__all__ = ["compatible_input_references", "input_reference_error"]
