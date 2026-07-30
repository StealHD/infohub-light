from __future__ import annotations

import json

import httpx
import pytest

from src.services.bilibili_user_search import (
    BILIBILI_HOME_URL,
    BILIBILI_USER_SEARCH_URL,
    MAX_BILIBILI_SEARCH_RESPONSE_BYTES,
    BilibiliUserSearchService,
)


def _search_payload(rows: list[dict], *, total: int | None = None) -> dict:
    return {
        "code": 0,
        "message": "OK",
        "data": {
            "numResults": len(rows) if total is None else total,
            "result": rows,
        },
    }


def test_search_bootstraps_anonymous_cookie_and_resolves_one_exact_name():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == BILIBILI_HOME_URL:
            return httpx.Response(
                200,
                headers={
                    "Set-Cookie": "buvid3=anonymous-device; Domain=.bilibili.com; Path=/"
                },
            )
        assert request.url.copy_with(query=None) == httpx.URL(
            BILIBILI_USER_SEARCH_URL
        )
        assert dict(request.url.params) == {
            "search_type": "bili_user",
            "keyword": "食贫道",
            "page": "1",
        }
        assert request.headers["cookie"] == "buvid3=anonymous-device"
        assert request.headers["referer"] == "https://search.bilibili.com/"
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {
                        "mid": 39627524,
                        "uname": '<em class="keyword">食贫道</em>',
                        "fans": 9_555_368,
                        "videos": 686,
                        "usign": "must not be projected",
                    },
                    {
                        "mid": 3546764420320129,
                        "uname": "食贫道SavorAround",
                    },
                ],
                total=21,
            ),
        )

    service = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler)
    )

    result = service.search(query="  食贫道  ")

    assert result == {
        "schema_version": 1,
        "query": "食贫道",
        "availability": "available",
        "match_status": "exact",
        "resolved_user": {
            "uid": "39627524",
            "name": "食贫道",
            "profile_url": "https://space.bilibili.com/39627524",
        },
        "candidates": [
            {
                "uid": "39627524",
                "name": "食贫道",
                "profile_url": "https://space.bilibili.com/39627524",
                "exact_name_match": True,
            },
            {
                "uid": "3546764420320129",
                "name": "食贫道SavorAround",
                "profile_url": "https://space.bilibili.com/3546764420320129",
                "exact_name_match": False,
            },
        ],
        "returned": 2,
        "truncated": True,
        "data_trust": "untrusted_public_metadata",
        "error_code": None,
    }
    assert len(requests) == 2
    serialized = json.dumps(result, ensure_ascii=False)
    assert "usign" not in serialized
    assert "fans" not in serialized
    assert "videos" not in serialized


def test_avatar_lookup_matches_uid_and_keeps_remote_url_out_of_public_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BILIBILI_HOME_URL:
            return httpx.Response(200)
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {
                        "mid": 39627524,
                        "uname": "食贫道",
                        "upic": "//i0.hdslb.com/bfs/face/avatar.jpg",
                    },
                    {
                        "mid": 383578614,
                        "uname": "超Carry的柴西",
                        "upic": "https://evil.example/avatar.jpg",
                    },
                ]
            ),
        )

    service = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler)
    )

    public = service.search(query="食贫道")

    assert "hdslb" not in json.dumps(public)
    assert service.avatar_for_uid(
        query="食贫道",
        uid="39627524",
    ) == "https://i0.hdslb.com/bfs/face/avatar.jpg"
    assert service.avatar_for_uid(query="食贫道", uid="383578614") is None
    assert service.avatar_for_uid(query="食贫道", uid="1") is None


def test_search_never_resolves_ambiguous_exact_names_and_honors_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BILIBILI_HOME_URL:
            return httpx.Response(
                200,
                headers={
                    "Set-Cookie": "buvid3=anonymous-device; Domain=.bilibili.com; Path=/"
                },
            )
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {"mid": 1, "uname": "同名账号"},
                    {"mid": 2, "uname": "同名账号"},
                    {"mid": 3, "uname": "同名账号备用"},
                ]
            ),
        )

    result = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler)
    ).search(query="同名账号", limit=2)

    assert result["match_status"] == "candidates"
    assert result["resolved_user"] is None
    assert [candidate["uid"] for candidate in result["candidates"]] == [
        "1",
        "2",
    ]
    assert result["returned"] == 2
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "query,limit",
    [
        ("", 5),
        ("https://space.bilibili.com/39627524", 5),
        ("x" * 51, 5),
        ("食贫道", 0),
        ("食贫道", 6),
        ("食贫道", True),
    ],
)
def test_search_rejects_non_name_or_out_of_range_inputs_without_network(
    query, limit
):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be used")

    service = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ValueError):
        service.search(query=query, limit=limit)


@pytest.mark.parametrize(
    "search_response",
    [
        httpx.Response(412),
        httpx.Response(200, json={"code": -412, "message": "request was banned"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(
            200,
            content=b"x" * (MAX_BILIBILI_SEARCH_RESPONSE_BYTES + 1),
        ),
    ],
)
def test_search_degrades_safely_for_unavailable_or_invalid_upstream(
    search_response: httpx.Response,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BILIBILI_HOME_URL:
            return httpx.Response(
                200,
                headers={
                    "Set-Cookie": "buvid3=anonymous-device; Domain=.bilibili.com; Path=/"
                },
            )
        return search_response

    result = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler)
    ).search(query="食贫道")

    assert result == {
        "schema_version": 1,
        "query": "食贫道",
        "availability": "unavailable",
        "match_status": "unavailable",
        "resolved_user": None,
        "candidates": [],
        "returned": 0,
        "truncated": False,
        "data_trust": "untrusted_public_metadata",
        "error_code": "bilibili_search_unavailable",
    }


def test_search_caches_success_without_leaking_mutable_results():
    now = [100.0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if str(request.url) == BILIBILI_HOME_URL:
            return httpx.Response(
                200,
                headers={
                    "Set-Cookie": "buvid3=anonymous-device; Domain=.bilibili.com; Path=/"
                },
            )
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {"mid": 1, "uname": "账号"},
                    {"mid": 2, "uname": "账号二"},
                    {"mid": 3, "uname": "账号三"},
                ]
            ),
        )

    service = BilibiliUserSearchService(
        transport=httpx.MockTransport(handler),
        clock=lambda: now[0],
    )
    first = service.search(query="账号", limit=5)
    first["candidates"].clear()
    second = service.search(query="账号", limit=2)

    assert calls == 2
    assert [candidate["uid"] for candidate in second["candidates"]] == [
        "1",
        "2",
    ]
    assert second["returned"] == 2
    assert second["truncated"] is True
