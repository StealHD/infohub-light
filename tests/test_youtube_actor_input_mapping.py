"""YouTube Build inputs are explicitly mapped, never borrowed from X."""

from src.services.apify_actor_manifest import ActorRuntime, ActorTarget, render_actor_input
from src.services.apify_actor_youtube_input import (
    input_template_for_registered_route,
    youtube_channel_items_input_template,
)


TARGET = ActorTarget(
    canonical_url="https://www.youtube.com/@YouTube",
    native_id="UCBR8-60-B28hp2BmDPdntcQ",
    handle="YouTube",
)


def _render(template: dict) -> dict:
    return render_actor_input(
        {
            "version": 1,
            "actor_id": "solidcode/youtube-scraper",
            "build_number": "1.0.31",
            "input": template,
            "output": {
                "native_id": {"pointers": ["/videoId"]},
                "url": {"pointers": ["/videoUrl"]},
                "published_at": {"pointers": ["/publishedAt"]},
                "title": {"pointers": ["/title"]},
                "source_native_id": {"pointers": ["/channelId"]},
            },
            "semantics": {
                "identity": {
                    "output_field": "source_native_id",
                    "target_ref": "target.native_id",
                    "match": "exact",
                },
                "url_host_allowlist": ["youtube.com", "youtu.be"],
            },
        },
        TARGET,
        ActorRuntime(max_items=1),
    )


def test_youtube_string_list_build_renders_real_channel_url_not_x_start_url_object() -> None:
    template = youtube_channel_items_input_template(
        {
            "type": "object",
            "required": ["startUrls"],
            "properties": {
                "startUrls": {"type": "array", "editor": "stringList"},
                "maxResults": {"type": "integer"},
                "fetchChannelInfo": {"type": "boolean"},
                "channelContent": {
                    "type": "string",
                    "enum": ["default", "videos", "shorts"],
                },
            },
        }
    )

    assert template == {
        "startUrls": [{"$ref": "target.canonical_url"}],
        "maxResults": {"$ref": "runtime.max_items"},
        "fetchChannelInfo": False,
        "channelContent": "videos",
    }
    assert _render(template) == {
        "startUrls": ["https://www.youtube.com/@YouTube"],
        "maxResults": 1,
        "fetchChannelInfo": False,
        "channelContent": "videos",
    }


def test_youtube_channel_id_and_url_forms_are_explicit_and_safe() -> None:
    assert youtube_channel_items_input_template(
        {
            "type": "object",
            "properties": {
                "channelIds": {"type": "array", "items": {"type": "string"}},
                "maxVideosPerChannel": {"type": "integer"},
            },
        }
    ) == {
        "channelIds": [{"$ref": "target.native_id"}],
        "maxVideosPerChannel": {"$ref": "runtime.max_items"},
    }
    assert youtube_channel_items_input_template(
        {"type": "object", "properties": {"startUrls": {"type": "array"}}}
    ) == {}


def test_unregistered_route_cannot_inherit_another_platform_input_dialect() -> None:
    schema = {"type": "object", "properties": {"url": {"type": "string"}}}

    assert input_template_for_registered_route(
        "unknown", "channel", "items", schema, lambda _schema: {"wrong": True}
    ) == {}
