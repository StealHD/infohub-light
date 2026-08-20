"""YouTube Build inputs are explicitly mapped, never borrowed from X."""

from src.services.apify_actor_discovery import _input_template_from_schema
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


def test_youtube_channel_and_channels_url_fields_are_mapped() -> None:
    """Common ``channel`` / ``channels`` URL fields must not be rejected."""

    assert youtube_channel_items_input_template(
        {
            "type": "object",
            "properties": {
                "channels": {"type": "array", "items": {"type": "string"}},
                "maxResults": {"type": "integer"},
            },
        }
    ) == {
        "channels": [{"$ref": "target.canonical_url"}],
        "maxResults": {"$ref": "runtime.max_items"},
    }
    assert youtube_channel_items_input_template(
        {"type": "object", "properties": {"channel": {"type": "string"}}}
    ) == {"channel": {"$ref": "target.canonical_url"}}


def test_youtube_channel_urls_or_ids_and_channel_inputs_are_mapped() -> None:
    """Real Store field names ``channelUrlsOrIds`` / ``channelInputs`` map to URL."""

    assert youtube_channel_items_input_template(
        {
            "type": "object",
            "properties": {
                "channelUrlsOrIds": {"type": "array", "editor": "stringList"},
                "maxItems": {"type": "integer"},
            },
        }
    ) == {
        "channelUrlsOrIds": [{"$ref": "target.canonical_url"}],
        "maxItems": {"$ref": "runtime.max_items"},
    }
    assert youtube_channel_items_input_template(
        {
            "type": "object",
            "properties": {
                "channelInputs": {"type": "array", "items": {"type": "string"}},
            },
        }
    ) == {"channelInputs": [{"$ref": "target.canonical_url"}]}


def test_youtube_handle_and_username_stay_unmapped() -> None:
    """Channel identity is native_id; handle/username must not be guessed."""

    assert youtube_channel_items_input_template(
        {"type": "object", "properties": {"handle": {"type": "string"}}}
    ) == {}
    assert youtube_channel_items_input_template(
        {"type": "object", "properties": {"username": {"type": "string"}}}
    ) == {}


def test_generic_input_template_maps_x_screen_name_not_user_id() -> None:
    """``screenName`` is a handle; ``userId`` needs native_id X does not expose."""

    assert _input_template_from_schema(
        {"type": "object", "properties": {"screenName": {"type": "string"}}}
    ) == {"screenName": {"$ref": "target.handle"}}
    assert _input_template_from_schema(
        {"type": "object", "properties": {"userId": {"type": "string"}}}
    ) == {}
    assert _input_template_from_schema(
        {"type": "object", "properties": {"authorId": {"type": "string"}}}
    ) == {}
