import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from src.services.youtube_channel import (
    YOUTUBE_RESOLVE_MAX_BYTES,
    YOUTUBE_RESOLVE_TIMEOUT_SECONDS,
    YouTubeChannelError,
    YouTubeChannelResolver,
)


CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
CANONICAL_URL = (
    "https://www.youtube.com/feeds/videos.xml?"
    f"channel_id={CHANNEL_ID}"
)


@pytest.mark.parametrize(
    "value",
    [
        CHANNEL_ID,
        f"https://youtube.com/channel/{CHANNEL_ID}",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/videos",
        f"https://youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}",
        CANONICAL_URL,
    ],
)
def test_direct_channel_identities_canonicalize_without_network(value):
    fetcher = AsyncMock()
    resolver = YouTubeChannelResolver(fetcher=fetcher)

    config = asyncio.run(resolver.resolve_config({"url": value}))

    assert config["url"] == CANONICAL_URL
    assert config["name"] == CANONICAL_URL
    assert config["keep_latest_item"] is True
    fetcher.assert_not_awaited()


@pytest.mark.parametrize(
    ("value", "expected_page"),
    [
        ("@GoogleDevelopers", "https://www.youtube.com/@GoogleDevelopers"),
        (
            "https://youtube.com/@GoogleDevelopers/shorts",
            "https://www.youtube.com/@GoogleDevelopers",
        ),
    ],
)
def test_handle_resolution_uses_one_fixed_bounded_public_page_request(
    value,
    expected_page,
):
    fetcher = AsyncMock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                '<html><head><link rel="alternate" '
                'type="application/rss+xml" '
                f'href="{CANONICAL_URL}"></head></html>'
            ),
            request=httpx.Request("GET", expected_page),
        )
    )
    resolver = YouTubeChannelResolver(fetcher=fetcher)

    config = asyncio.run(
        resolver.resolve_config({"url": value, "keep_latest_item": False})
    )

    assert config["url"] == CANONICAL_URL
    assert config["keep_latest_item"] is False
    fetcher.assert_awaited_once()
    args, kwargs = fetcher.await_args
    assert args == (expected_page,)
    assert kwargs["timeout"] == YOUTUBE_RESOLVE_TIMEOUT_SECONDS
    assert kwargs["max_response_bytes"] == YOUTUBE_RESOLVE_MAX_BYTES
    assert kwargs["max_redirects"] == 0
    assert kwargs["headers"]["Accept"].startswith("text/html")


@pytest.mark.parametrize(
    "value",
    [
        "http://www.youtube.com/@GoogleDevelopers",
        "https://youtu.be/example",
        "https://www.youtube.com/watch?v=example",
        "https://www.youtube.com/shorts/example",
        "https://www.youtube.com/playlist?list=PLexample",
        "https://www.youtube.com:443/@GoogleDevelopers",
        "https://user@example.com/@GoogleDevelopers",
        "https://www.youtube.com/@GoogleDevelopers?feature=shared",
        "https://www.youtube.com/@GoogleDevelopers#about",
        "GoogleDevelopers",
    ],
)
def test_unsupported_or_ambiguous_inputs_are_safe_input_errors(value):
    fetcher = AsyncMock()
    resolver = YouTubeChannelResolver(fetcher=fetcher)

    with pytest.raises(YouTubeChannelError) as exc_info:
        asyncio.run(resolver.resolve_config({"url": value}))

    assert exc_info.value.code == "invalid_source_config"
    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False
    fetcher.assert_not_awaited()


@pytest.mark.parametrize(
    "config",
    [
        {"url": "@GoogleDevelopers", "cookie": "never"},
        {"url": "@GoogleDevelopers", "headers": {"Authorization": "never"}},
        {
            "url": "https://www.youtube.com/@GoogleDevelopers"
            "?access_token=never"
        },
    ],
)
def test_setup_rejects_credentials_and_unsupported_fields_before_network(
    config,
):
    fetcher = AsyncMock()

    with pytest.raises(YouTubeChannelError) as exc_info:
        asyncio.run(
            YouTubeChannelResolver(fetcher=fetcher).resolve_config(config)
        )

    assert exc_info.value.code == "invalid_source_config"
    assert "never" not in str(exc_info.value)
    fetcher.assert_not_awaited()


def test_missing_feed_link_is_stable_not_found_without_echoing_html():
    secret_marker = "do-not-echo-upstream-body"
    fetcher = AsyncMock(
        return_value=httpx.Response(
            404,
            text=secret_marker,
            request=httpx.Request(
                "GET", "https://www.youtube.com/@MissingChannel"
            ),
        )
    )

    with pytest.raises(YouTubeChannelError) as exc_info:
        asyncio.run(
            YouTubeChannelResolver(fetcher=fetcher).resolve_config(
                {"url": "@MissingChannel"}
            )
        )

    assert exc_info.value.code == "youtube_channel_not_found"
    assert exc_info.value.status_code == 404
    assert secret_marker not in str(exc_info.value)


def test_upstream_and_redirect_failures_are_stable_and_retryable():
    request = httpx.Request("GET", "https://www.youtube.com/@Temporary")
    for result in (
        httpx.Response(302, headers={"location": "/redirect"}, request=request),
        httpx.Response(503, text="private upstream detail", request=request),
        httpx.ConnectError("private transport detail", request=request),
    ):
        fetcher = AsyncMock(
            side_effect=result if isinstance(result, Exception) else None,
            return_value=None if isinstance(result, Exception) else result,
        )
        with pytest.raises(YouTubeChannelError) as exc_info:
            asyncio.run(
                YouTubeChannelResolver(fetcher=fetcher).resolve_config(
                    {"url": "@Temporary"}
                )
            )
        assert exc_info.value.code == "youtube_channel_resolution_failed"
        assert exc_info.value.status_code == 502
        assert exc_info.value.retryable is True
        assert "private" not in str(exc_info.value)
