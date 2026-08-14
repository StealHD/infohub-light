"""Deterministic, free X compatibility-candidate admission checks.

Compatibility relaxes the number of Actors and AI Manifest availability.  It
does not relax the public Build contract: an item must be viable before the UI
can offer its paid Canary action.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_KNOWN_X_INPUT_DIALECTS = frozenset(
    {
        "twitter_handles",
        "start_urls",
        "profile_urls",
        "twitter_handle",
        "username",
        "handle",
        "direct_urls",
        "urls",
        "url",
    }
)
_X_PROFILE_NEGATIVE_TERMS = frozenset(
    {
        "bluesky",
        "comment",
        "contact",
        "email",
        "facebook",
        "follower",
        "following",
        "instagram",
        "lead",
        "linkedin",
        "phone",
        "pinterest",
        "quote",
        "reddit",
        "repl",
        "search",
        "tiktok",
        "youtube",
    }
)
_X_PROFILE_REQUIRED_GROUPS = (
    frozenset({"x", "twitter"}),
    frozenset({"profile", "user", "handle"}),
    frozenset({"post", "tweet", "feed"}),
)


def compatibility_input_dialect(schema: Mapping[str, Any]) -> str | None:
    """Return a known X profile input dialect, never a guessed fallback."""

    properties = schema.get("properties")
    fields = properties if isinstance(properties, Mapping) else schema
    normalized = {
        re.sub(r"[^a-z0-9]+", "", str(name).casefold())
        for name in list(fields)[:128]
    }
    for field_name, dialect in (
        ("twitterhandles", "twitter_handles"),
        ("starturls", "start_urls"),
        ("profileurls", "profile_urls"),
        ("twitterhandle", "twitter_handle"),
        ("username", "username"),
        ("handle", "handle"),
        ("directurls", "direct_urls"),
        ("urls", "urls"),
        ("url", "url"),
    ):
        if field_name in normalized:
            return dialect
    return None


def compatibility_count_field(schema: Mapping[str, Any]) -> str | None:
    """Return the exact bounded count field advertised by the Build."""

    properties = schema.get("properties")
    fields = properties if isinstance(properties, Mapping) else schema
    allowed = (
        "maxItems",
        "max_items",
        "maxResults",
        "max_results",
        "resultsLimit",
        "limit",
        "tweetsDesired",
    )
    return next((field for field in allowed if field in fields), None)


def compatibility_preflight_failure(
    *,
    actor_id: str,
    actor: Mapping[str, Any],
    build_id: str,
    tagged_build_number: str,
    build: Mapping[str, Any],
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any],
    input_template: Mapping[str, Any],
    input_dialect: str | None,
    output_schema_proves_items: bool,
) -> str | None:
    """Return a deterministic zero-cost rejection reason, if any.

    This admission layer deliberately applies only facts the Store exposes for
    free.  Result identity remains the paid Canary's responsibility.
    """

    metadata_failure = compatibility_metadata_failure(actor)
    if metadata_failure is not None:
        return metadata_failure
    if str(actor.get("actorPermissionLevel") or "").casefold() != "limited_permissions":
        return "actor_requires_limited_permissions"
    if not build_id or not tagged_build_number:
        return "actor_exact_build_missing"
    if str(build.get("status") or "").upper() != "SUCCEEDED":
        return "actor_build_not_successful"
    if str(build.get("buildNumber") or "") != tagged_build_number:
        return "actor_build_identity_mismatch"
    if not input_schema or not output_schema:
        return "actor_schema_unverifiable"
    if not input_template or input_dialect not in _KNOWN_X_INPUT_DIALECTS:
        return "actor_input_schema_unmappable"
    if not output_schema_proves_items:
        return "actor_output_contract_unverifiable"
    return _x_profile_semantic_failure(actor_id, actor)


def compatibility_metadata_failure(actor: Mapping[str, Any]) -> str | None:
    """Reject an already-known deprecated Actor before a Build lookup."""

    if actor.get("isDeprecated") is not False:
        return (
            "actor_deprecated"
            if actor.get("isDeprecated") is True
            else "actor_deprecation_unverifiable"
        )
    return None


def render_compatibility_input(
    template: Mapping[str, Any],
    *,
    canonical_url: str,
    native_id: str,
    handle: str,
    max_items: int,
) -> dict[str, Any]:
    """Render the schema-derived input without requiring an AI Manifest.

    The template originates from the exact Build schema.  Only the three
    ordinary target references and the bounded max-items reference are legal.
    """

    references = {
        "target.canonical_url": canonical_url,
        "target.native_id": native_id,
        "target.handle": handle,
        "runtime.max_items": int(max_items),
    }

    def visit(value: Any, *, depth: int) -> Any:
        if depth > 12:
            raise ValueError("compatibility input exceeds nesting limit")
        if isinstance(value, Mapping):
            if set(value) == {"$ref"}:
                reference = value.get("$ref")
                if not isinstance(reference, str) or reference not in references:
                    raise ValueError("compatibility input contains an unknown reference")
                return references[reference]
            return {
                str(key): visit(item, depth=depth + 1)
                for key, item in value.items()
                if isinstance(key, str)
            }
        if isinstance(value, list):
            return [visit(item, depth=depth + 1) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError("compatibility input contains an unsupported literal")

    rendered = visit(template, depth=0)
    if not isinstance(rendered, dict):
        raise ValueError("compatibility input must be an object")
    return rendered


def _x_profile_semantic_failure(
    actor_id: str, actor: Mapping[str, Any]
) -> str | None:
    identity_values = (
        actor_id,
        actor.get("name"),
        actor.get("actorName"),
        actor.get("title"),
    )
    description = actor.get("description")
    identity_words = _semantic_words(identity_values)
    all_words = _semantic_words((*identity_values, description))
    if any(
        word == term or word.startswith(term)
        for word in identity_words
        for term in _X_PROFILE_NEGATIVE_TERMS
    ):
        return "actor_x_profile_semantics_mismatch"
    if not all(
        any(
            word == term or word.startswith(term)
            for word in all_words
            for term in group
        )
        for group in _X_PROFILE_REQUIRED_GROUPS
    ):
        return "actor_x_profile_semantics_unverifiable"
    return None


def _semantic_words(values: tuple[Any, ...]) -> set[str]:
    return set(
        re.findall(
            r"[a-z0-9]+",
            " ".join(str(value or "") for value in values).casefold(),
        )
    )


__all__ = [
    "compatibility_count_field",
    "compatibility_input_dialect",
    "compatibility_metadata_failure",
    "compatibility_preflight_failure",
    "render_compatibility_input",
]
