"""Pure user/subscription projection for neutral source content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _source_value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _projection_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in value
            if (text := str(item).strip())
        )
    )


@dataclass(frozen=True, slots=True)
class TargetSubscriptionProjection:
    """Target-owned fields applied after neutral content acquisition."""

    source_id: str
    subscription_id: str | None
    source_key: str | None
    source_display_name: str | None
    catalog_source_type: str | None
    source_priority: int
    channel: str | None
    topics: tuple[str, ...]
    personal_tags: tuple[str, ...]
    analysis_mode: str

    def metadata(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "topics": list(self.topics),
            "tags": list(self.topics),
            "configured_topics": list(self.topics),
            "personal_tags": list(self.personal_tags),
            "source_id": self.source_id,
            "subscription_id": self.subscription_id,
            "source_key": self.source_key,
            "source_display_name": self.source_display_name,
            "catalog_source_type": self.catalog_source_type,
            "source_priority": self.source_priority,
            "analysis_mode": self.analysis_mode,
            **(
                {"show_in_personal_feed": True}
                if self.analysis_mode == "personal_only"
                else {}
            ),
        }


def target_subscription_projection(source: Any) -> TargetSubscriptionProjection:
    """Compute the complete user/subscription projection without side effects."""

    analysis_mode = _source_value(source, "analysis_mode", "full")
    if hasattr(analysis_mode, "value"):
        analysis_mode = analysis_mode.value
    analysis_mode = (
        "personal_only" if str(analysis_mode) == "personal_only" else "full"
    )
    channel_value = (
        _source_value(source, "override_channel")
        or _source_value(source, "hub_channel")
        or _source_value(source, "channel")
        or _source_value(source, "category")
        or _source_value(source, "default_channel")
    )
    override_topics = _projection_strings(
        _source_value(source, "override_topics")
    )
    configured_topics = (
        override_topics
        or _projection_strings(_source_value(source, "topics"))
        or _projection_strings(_source_value(source, "default_topics"))
    )
    topics = list(configured_topics)
    for tag in _projection_strings(_source_value(source, "tags")):
        if tag not in topics:
            topics.append(tag)
    source_priority = _source_value(source, "source_priority")
    if source_priority is None:
        source_priority = _source_value(source, "priority", 0)
    source_display_name = (
        _source_value(source, "source_display_name")
        or _source_value(source, "display_name")
    )
    catalog_source_type = (
        _source_value(source, "catalog_source_type")
        or _source_value(source, "type")
        or _source_value(source, "source_type")
    )
    subscription_id = _source_value(source, "subscription_id")
    source_key = _source_value(source, "source_key")
    return TargetSubscriptionProjection(
        source_id=str(_source_value(source, "source_id") or ""),
        subscription_id=(
            str(subscription_id) if subscription_id not in {None, ""} else None
        ),
        source_key=str(source_key) if source_key not in {None, ""} else None,
        source_display_name=(
            str(source_display_name)
            if source_display_name not in {None, ""}
            else None
        ),
        catalog_source_type=(
            str(catalog_source_type)
            if catalog_source_type not in {None, ""}
            else None
        ),
        source_priority=int(source_priority or 0),
        channel=(
            str(channel_value).strip()
            if channel_value not in {None, ""} and str(channel_value).strip()
            else None
        ),
        topics=tuple(topics),
        personal_tags=_projection_strings(
            _source_value(source, "personal_tags")
        ),
        analysis_mode=analysis_mode,
    )
