"""Schema-proven YouTube channel coverage and ordering inputs."""

from __future__ import annotations

from collections.abc import Mapping


_CHANNEL_INPUTS = frozenset({
    "channelId", "channelIds", "channelUrls", "channel_urls", "channelUrl",
    "channel_url", "channelInputs", "channels", "channelUsername",
    "channelHandle", "startUrls", "channel", "url",
})


def apply_youtube_input_capabilities(
    input_template: Mapping[str, object], input_schema: Mapping[str, object]
) -> dict[str, object]:
    """Add only exact public-enum literals for channel mode and latest/all output."""

    result = dict(input_template)
    if not _CHANNEL_INPUTS.intersection(result):
        return result
    properties = input_schema.get("properties")
    if not isinstance(properties, Mapping):
        return result
    for field, literal in (
        ("scrape_type", "channels"),
        ("contentType", "all"),
        ("sortBy", "newest"),
        ("sortOrder", "latest"),
    ):
        if _enum_contains(properties.get(field), literal):
            result[field] = literal
    return result


def proves_combined_latest_items(input_template: Mapping[str, object]) -> bool:
    """Return whether one Manifest explicitly proves Shorts-inclusive latest order."""

    return (
        input_template.get("contentType") == "all"
        and (
            input_template.get("sortBy") == "newest"
            or input_template.get("sortOrder") == "latest"
        )
    )


def _enum_contains(raw_schema: object, literal: str) -> bool:
    if not isinstance(raw_schema, Mapping):
        return False
    values = raw_schema.get("enum")
    return isinstance(values, list) and literal in values


__all__ = [
    "apply_youtube_input_capabilities",
    "proves_combined_latest_items",
]
