from __future__ import annotations

import asyncio
import gzip
import hashlib
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from src.models import RSSSourceConfig
from src.scrapers.rss import RSSScraper
from src.services import network_policy


def _fetch_selection_feed(
    entries: list[tuple[str, str]],
    *,
    keep_latest_item: bool,
    since: datetime,
):
    xml_items = "".join(
        f"""
        <item><guid>{title}</guid><title>{title}</title>
          <link>https://example.com/{title.replace(' ', '-')}</link>
          <pubDate>{published}</pubDate><description>{title}</description>
        </item>
        """
        for title, published in entries
    )
    response = MagicMock()
    response.text = (
        f"<rss version='2.0'><channel><title>Selection</title>{xml_items}</channel></rss>"
    )
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Selection",
        url="https://example.com/selection.xml",
        keep_latest_item=keep_latest_item,
    )
    return asyncio.run(RSSScraper([source], client).fetch(since))


def test_rss_default_does_not_backfill_items_before_window() -> None:
    items = _fetch_selection_feed(
        [
            ("Older item", "Thu, 02 Jul 2026 09:00:00 GMT"),
            ("Newest old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
        ],
        keep_latest_item=False,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert items == []


def test_personal_rss_backfills_only_newest_dated_item_when_window_is_empty() -> None:
    items = _fetch_selection_feed(
        [
            ("Newest old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
            ("Older item", "Thu, 02 Jul 2026 09:00:00 GMT"),
        ],
        keep_latest_item=True,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert [item.title for item in items] == ["Newest old item"]
    assert items[0].metadata["retention_policy"] == "latest_per_source"


def test_personal_rss_returns_all_in_window_items_and_marks_only_newest() -> None:
    items = _fetch_selection_feed(
        [
            ("Recent two", "Wed, 15 Jul 2026 12:00:00 GMT"),
            ("Old item", "Thu, 09 Jul 2026 09:00:00 GMT"),
            ("Recent one", "Wed, 15 Jul 2026 08:00:00 GMT"),
        ],
        keep_latest_item=True,
        since=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert {item.title for item in items} == {"Recent one", "Recent two"}
    assert [
        item.title
        for item in items
        if item.metadata.get("retention_policy") == "latest_per_source"
    ] == ["Recent two"]
    assert (
        next(item for item in items if item.title == "Recent one").metadata[
            "retention_policy"
        ]
        == "time_window"
    )


def test_rss_ids_are_deterministic() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0"><channel><title>Test</title>
      <item>
        <guid>entry-1</guid>
        <title>Item 1</title>
        <link>https://example.com/item-1</link>
        <pubDate>Fri, 24 Apr 2026 12:00:00 GMT</pubDate>
        <description>Hello</description>
      </item>
    </channel></rss>
    """
    response = MagicMock()
    response.text = feed
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(name="Test", url="https://example.com/feed.xml")
    scraper = RSSScraper([source], client)
    since = datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc)

    first = asyncio.run(scraper.fetch(since))[0].id
    second = asyncio.run(scraper.fetch(since))[0].id

    assert first == second
    assert first == "rss:example.com_feed.xml:5e2d5d1e58e94d76"


def test_rss_items_preserve_service_scope_and_analysis_metadata() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0"><channel><title>Test</title>
      <item>
        <guid>entry-1</guid>
        <title>Item 1</title>
        <link>https://example.com/item-1</link>
        <pubDate>Fri, 24 Apr 2026 12:00:00 GMT</pubDate>
        <description>Hello</description>
      </item>
    </channel></rss>
    """
    response = MagicMock()
    response.text = feed
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Test",
        url="https://example.com/feed.xml",
        source_id="src_1",
        subscription_id="sub_1",
        source_key="rss:https://example.com/feed.xml",
        analysis_mode="personal_only",
        source_priority=73,
        source_display_name="Test Feed",
        catalog_source_type="rss",
    )

    item = asyncio.run(
        RSSScraper([source], client).fetch(
            datetime(2026, 4, 24, 0, 0, tzinfo=timezone.utc)
        )
    )[0]

    assert item.metadata["source_id"] == "src_1"
    assert item.metadata["subscription_id"] == "sub_1"
    assert item.metadata["source_key"] == "rss:https://example.com/feed.xml"
    assert item.metadata["analysis_mode"] == "personal_only"
    assert item.metadata["source_priority"] == 73
    assert item.metadata["source_display_name"] == "Test Feed"
    assert item.metadata["catalog_source_type"] == "rss"
    assert item.metadata["show_in_personal_feed"] is True


def test_rss_prefers_captured_full_content_and_projects_feed_media_and_icon() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
         xmlns:media="http://search.yahoo.com/mrss/">
      <channel><title>Media Feed</title>
        <image><url>https://cdn.example.com/feed-icon.png</url><title>Media</title><link>https://example.com</link></image>
        <item><guid>media-1</guid><title>Media item</title>
          <link>https://example.com/media-1</link>
          <pubDate>Fri, 24 Apr 2026 12:00:00 GMT</pubDate>
          <description>Short summary</description>
          <content:encoded><![CDATA[<p>Full captured body</p>]]></content:encoded>
          <media:content url="https://cdn.example.com/photo.jpg" type="image/jpeg" />
        </item>
      </channel>
    </rss>"""
    response = MagicMock()
    response.text = feed
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response

    item = asyncio.run(RSSScraper(
        [RSSSourceConfig(name="Media", url="https://example.com/media.xml")], client
    ).fetch(datetime(2026, 4, 24, tzinfo=timezone.utc)))[0]

    assert item.content == "<p>Full captured body</p>"
    assert item.metadata["feed_icon_url"] == "https://cdn.example.com/feed-icon.png"
    assert item.metadata["media_urls"] == ["https://cdn.example.com/photo.jpg"]
    assert item.metadata["image_url"] == "https://cdn.example.com/photo.jpg"
    assert item.metadata["media_image_count"] == 1
    assert item.metadata["upstream_content_format"] == "image"


def test_rss_video_enclosure_does_not_count_thumbnail_as_an_image() -> None:
    inventory = RSSScraper._extract_media_inventory(
        {
            "enclosures": [{"url": "https://cdn.example.com/movie.mp4", "type": "video/mp4"}],
            "media_thumbnail": [{"url": "https://cdn.example.com/poster.jpg"}],
        },
        '<img src="https://cdn.example.com/poster.jpg">',
        "https://www.youtube.com/watch?v=example",
    )

    assert inventory == {
        "image_urls": [],
        "image_count": 0,
        "video_count": 1,
        "audio_count": 0,
        "format": "video",
    }


def test_service_source_priority_defaults_to_zero_and_rejects_out_of_range_values() -> None:
    assert RSSSourceConfig(name="Default", url="https://example.com/default.xml").source_priority == 0

    with pytest.raises(ValidationError, match="less than or equal to 100"):
        RSSSourceConfig(
            name="Too high",
            url="https://example.com/high.xml",
            source_priority=101,
        )


def test_rss_strict_mode_propagates_fetch_failure() -> None:
    request = httpx.Request("GET", "https://example.com/feed.xml")
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("offline", request=request)
    scraper = RSSScraper(
        [RSSSourceConfig(name="Test", url="https://example.com/feed.xml")],
        client,
    )
    scraper.strict_errors = True

    with pytest.raises(httpx.ConnectError, match="offline"):
        asyncio.run(scraper.fetch(datetime.now(timezone.utc)))


def test_member_controlled_rss_rejects_loopback_before_request() -> None:
    response = MagicMock()
    response.text = "<rss version='2.0'><channel></channel></rss>"
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Unsafe",
        url="http://127.0.0.1:8080/feed.xml",
        enforce_public_network=True,
    )
    scraper = RSSScraper([source], client)
    scraper.strict_errors = True

    with pytest.raises(ValueError, match="public network"):
        asyncio.run(scraper.fetch(datetime.now(timezone.utc)))

    client.get.assert_not_awaited()


def test_synthetic_dns_is_limited_to_explicit_cdn_suffixes(monkeypatch) -> None:
    def resolve_fake_ip(host, port, *, type):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("198.18.0.120", port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve_fake_ip)

    with pytest.raises(ValueError, match="public network"):
        network_policy.resolve_public_http_url(
            "https://instagram.flas1-1.fna.fbcdn.net/photo.jpg"
        )

    target = network_policy.resolve_public_http_url(
        "https://instagram.flas1-1.fna.fbcdn.net/photo.jpg",
        synthetic_dns_host_suffixes=("fbcdn.net",),
    )
    assert target.addresses == ("198.18.0.120",)

    with pytest.raises(ValueError, match="public network"):
        network_policy.resolve_public_http_url(
            "https://attacker.example/photo.jpg",
            synthetic_dns_host_suffixes=("fbcdn.net",),
        )


def test_trusted_rss_keeps_private_network_compatibility() -> None:
    response = MagicMock(status_code=200, headers={})
    response.text = "<rss version='2.0'><channel></channel></rss>"
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Trusted local",
        url="http://127.0.0.1:8080/feed.xml",
        enforce_public_network=False,
    )

    result = asyncio.run(RSSScraper([source], client).fetch(datetime.now(timezone.utc)))

    assert result == []
    client.get.assert_awaited_once_with(
        "http://127.0.0.1:8080/feed.xml",
        follow_redirects=True,
    )


def test_managed_rsshub_route_disables_redirect_following(monkeypatch) -> None:
    monkeypatch.delenv("RSSHUB_ACCESS_KEY", raising=False)
    response = MagicMock(status_code=200, headers={})
    response.text = "<rss version='2.0'><channel></channel></rss>"
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Bilibili",
        url="http://rsshub:1200/bilibili/user/video/39627524/1",
        provider="rsshub",
        site="bilibili",
        route_key="user_video",
        params={"uid": "39627524"},
        source_key="rss:rsshub:bilibili:user_video:39627524",
        enforce_public_network=False,
    )

    result = asyncio.run(
        RSSScraper([source], client).fetch(datetime.now(timezone.utc))
    )

    assert result == []
    client.get.assert_awaited_once_with(
        "http://rsshub:1200/bilibili/user/video/39627524/1",
        follow_redirects=False,
    )


def test_managed_rsshub_route_uses_scoped_access_code(monkeypatch) -> None:
    access_key = "private-master-key"
    monkeypatch.setenv("RSSHUB_ACCESS_KEY", access_key)
    response = MagicMock(status_code=200, headers={})
    response.text = "<rss version='2.0'><channel></channel></rss>"
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    source = RSSSourceConfig(
        name="Bilibili",
        url="https://rsshub.example.com/prefix/bilibili/user/video/39627524/1",
        provider="rsshub",
        site="bilibili",
        route_key="user_video",
        params={"uid": "39627524"},
        source_key="rss:rsshub:bilibili:user_video:39627524",
        enforce_public_network=False,
    )

    result = asyncio.run(
        RSSScraper([source], client).fetch(datetime.now(timezone.utc))
    )

    route = "/bilibili/user/video/39627524/1"
    code = hashlib.md5(
        f"{route}{access_key}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    assert result == []
    client.get.assert_awaited_once_with(
        f"https://rsshub.example.com/prefix{route}?code={code}",
        follow_redirects=False,
    )
    assert access_key not in str(client.get.await_args)


def test_member_controlled_rss_validates_every_redirect_target() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal"})
        return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>")

    async def run() -> None:
        client = AsyncMock()
        source = RSSSourceConfig(
            name="Redirect",
            url="https://93.184.216.34/feed.xml",
            enforce_public_network=True,
        )
        scraper = RSSScraper(
            [source],
            client,
            public_http_transport_factory=lambda: httpx.MockTransport(handler),
        )
        scraper.strict_errors = True
        with pytest.raises(ValueError, match="public network"):
            await scraper.fetch(datetime.now(timezone.utc))
        client.get.assert_not_awaited()

    asyncio.run(run())

    assert calls == ["https://93.184.216.34/feed.xml"]


def test_member_controlled_rss_preserves_http_error_behavior() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    client = AsyncMock()
    source = RSSSourceConfig(
        name="Missing",
        url="https://93.184.216.34/missing.xml",
        enforce_public_network=True,
    )
    scraper = RSSScraper(
        [source],
        client,
        public_http_transport_factory=lambda: httpx.MockTransport(handler),
    )
    scraper.strict_errors = True

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scraper.fetch(datetime.now(timezone.utc)))

    client.get.assert_not_awaited()


def test_member_controlled_rss_connects_to_the_validated_ip_and_preserves_host_and_sni(
    monkeypatch,
) -> None:
    resolutions = 0

    def resolve(_host, port, *, type):
        nonlocal resolutions
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "127.0.0.1"
        return [(socket.AF_INET, type, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>")

    client = AsyncMock()
    source = RSSSourceConfig(
        name="Pinned",
        url="https://feeds.example.test/feed.xml",
        enforce_public_network=True,
    )

    result = asyncio.run(
        RSSScraper(
            [source],
            client,
            public_http_transport_factory=lambda: httpx.MockTransport(handler),
        ).fetch(datetime.now(timezone.utc))
    )

    assert result == []
    assert resolutions == 1
    assert str(requests[0].url) == "https://93.184.216.34/feed.xml"
    assert requests[0].headers["host"] == "feeds.example.test"
    assert requests[0].extensions["sni_hostname"] == "feeds.example.test"
    client.get.assert_not_awaited()


def test_member_controlled_rss_revalidates_and_pins_each_redirect_hop(monkeypatch) -> None:
    addresses = {
        "feeds.example.test": "93.184.216.34",
        "redirect.example.test": "1.1.1.1",
    }

    def resolve(host, port, *, type):
        address = addresses[host]
        return [(socket.AF_INET, type, socket.IPPROTO_TCP, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302,
                headers={"location": "https://redirect.example.test/next.xml"},
            )
        return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>")

    client = AsyncMock()
    source = RSSSourceConfig(
        name="Redirect",
        url="https://feeds.example.test/feed.xml",
        enforce_public_network=True,
    )

    result = asyncio.run(
        RSSScraper(
            [source],
            client,
            public_http_transport_factory=lambda: httpx.MockTransport(handler),
        ).fetch(datetime.now(timezone.utc))
    )

    assert result == []
    first, second = requests
    assert str(first.url) == "https://93.184.216.34/feed.xml"
    assert first.headers["host"] == "feeds.example.test"
    assert first.extensions["sni_hostname"] == "feeds.example.test"
    assert str(second.url) == "https://1.1.1.1/next.xml"
    assert second.headers["host"] == "redirect.example.test"
    assert second.extensions["sni_hostname"] == "redirect.example.test"
    client.get.assert_not_awaited()


def test_public_fetch_isolates_connection_pool_and_disables_proxies_per_hostname(
    monkeypatch,
) -> None:
    created_clients = []
    requests = []
    responses = [
        httpx.Response(
            302,
            headers={"location": "https://second.example.test/feed.xml"},
        ),
        httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>"),
    ]

    def resolve(_host, port, *, type):
        return [
            (socket.AF_INET, type, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
        ]

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.options = kwargs
            created_clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            requests.append((self, url, kwargs))
            template = responses[len(requests) - 1]
            request = httpx.Request(
                method,
                url,
                headers=kwargs.get("headers"),
                extensions=kwargs.get("extensions"),
            )
            yield httpx.Response(
                template.status_code,
                headers=template.headers,
                content=template.content,
                request=request,
            )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        network_policy,
        "httpx",
        SimpleNamespace(
            AsyncClient=FakeAsyncClient,
            Response=httpx.Response,
            TransportError=httpx.TransportError,
        ),
    )

    response = asyncio.run(
        network_policy.fetch_public_http("https://first.example.test/feed.xml")
    )

    assert response.status_code == 200
    assert len(created_clients) == 2
    assert all(client.options["trust_env"] is False for client in created_clients)
    assert requests[0][0] is not requests[1][0]
    assert requests[0][2]["extensions"]["sni_hostname"] == "first.example.test"
    assert requests[1][2]["extensions"]["sni_hostname"] == "second.example.test"


def test_public_fetch_rejects_response_body_over_two_megabytes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_000_001)

    with pytest.raises(ValueError, match="response exceeded"):
        asyncio.run(
            network_policy.fetch_public_http(
                "https://93.184.216.34/feed.xml",
                transport_factory=lambda: httpx.MockTransport(handler),
            )
        )


def test_public_fetch_rejects_compressed_body_before_automatic_decoding() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b"small feed"),
        )

    with pytest.raises(ValueError, match="content encoding"):
        asyncio.run(
            network_policy.fetch_public_http(
                "https://93.184.216.34/feed.xml",
                transport_factory=lambda: httpx.MockTransport(handler),
            )
        )

    assert requests[0].headers["accept-encoding"] == "identity"


def test_public_fetch_overrides_security_headers_case_insensitively() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"feed")

    asyncio.run(
        network_policy.fetch_public_http(
            "https://93.184.216.34/feed.xml",
            headers={"host": "attacker.example", "accept-encoding": "gzip"},
            transport_factory=lambda: httpx.MockTransport(handler),
        )
    )

    assert requests[0].headers.get_list("host") == ["93.184.216.34"]
    assert requests[0].headers.get_list("accept-encoding") == ["identity"]


def test_member_rss_private_host_requires_admin_environment_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_MEMBER_RSS_HOST_ALLOWLIST", "127.0.0.1")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="<rss version='2.0'><channel></channel></rss>")

    client = AsyncMock()
    source = RSSSourceConfig(
        name="Allowed local fixture",
        url="http://127.0.0.1:8080/feed.xml",
        enforce_public_network=True,
    )

    result = asyncio.run(
        RSSScraper(
            [source],
            client,
            public_http_transport_factory=lambda: httpx.MockTransport(handler),
        ).fetch(datetime.now(timezone.utc))
    )

    assert result == []
    assert str(requests[0].url) == "http://127.0.0.1:8080/feed.xml"
    assert requests[0].headers["host"] == "127.0.0.1:8080"
    client.get.assert_not_awaited()
