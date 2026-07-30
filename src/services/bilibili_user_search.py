"""Bounded public Bilibili user-name resolution for Remote MCP."""

from __future__ import annotations

import copy
import json
import threading
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx


BILIBILI_HOME_URL = "https://www.bilibili.com/"
BILIBILI_USER_SEARCH_URL = (
    "https://api.bilibili.com/x/web-interface/search/type"
)
MAX_BILIBILI_SEARCH_RESPONSE_BYTES = 512_000
MAX_BILIBILI_QUERY_CHARS = 50
MAX_BILIBILI_CANDIDATES = 5

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/126.0 Safari/537.36"
)


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    expires_at: float
    result: dict[str, Any]


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _normalize_query(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("query must be a string")
    query = _normalize_text(value)
    if (
        not query
        or len(query) > MAX_BILIBILI_QUERY_CHARS
        or "://" in query
        or any(ord(character) < 32 for character in query)
    ):
        raise ValueError("query must be a bounded Bilibili account name")
    return query


def _plain_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parser = _PlainTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return None
    name = _normalize_text("".join(parser.parts))
    return name if 0 < len(name) <= 80 else None


def _positive_uid(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    candidate = str(value)
    if (
        not candidate.isascii()
        or not candidate.isdigit()
        or candidate.startswith("0")
        or len(candidate) > 19
    ):
        return None
    return candidate


def _avatar_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if raw.startswith("//"):
        raw = f"https:{raw}"
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname.endswith(".hdslb.com")
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/bfs/face/")
    ):
        return None
    return urlunsplit(("https", hostname, parsed.path, parsed.query, ""))


class BilibiliUserSearchService:
    """Resolve public account names through fixed Bilibili endpoints only."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _unavailable(query: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "query": query,
            "availability": "unavailable",
            "match_status": "unavailable",
            "resolved_user": None,
            "candidates": [],
            "returned": 0,
            "truncated": False,
            "data_trust": "untrusted_public_metadata",
            "error_code": "bilibili_search_unavailable",
        }

    @staticmethod
    def _read_bounded_json(response: httpx.Response) -> dict[str, Any] | None:
        if response.status_code != 200:
            return None
        if response.headers.get("content-encoding", "identity").lower() not in {
            "",
            "identity",
        }:
            return None
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_BILIBILI_SEARCH_RESPONSE_BYTES:
                    return None
            except ValueError:
                return None
        payload = bytearray()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > MAX_BILIBILI_SEARCH_RESPONSE_BYTES:
                return None
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _request(self, query: str, limit: int) -> dict[str, Any]:
        client_options: dict[str, Any] = {
            "timeout": httpx.Timeout(8.0, connect=4.0),
            "follow_redirects": False,
            "trust_env": False,
            "headers": {
                "User-Agent": _USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Accept-Encoding": "identity",
            },
        }
        if self._transport is not None:
            client_options["transport"] = self._transport
        try:
            with httpx.Client(**client_options) as client:
                with client.stream(
                    "GET",
                    BILIBILI_HOME_URL,
                    headers={"Accept": "text/html"},
                ) as bootstrap:
                    if bootstrap.status_code != 200:
                        return self._unavailable(query)
                with client.stream(
                    "GET",
                    BILIBILI_USER_SEARCH_URL,
                    params={
                        "search_type": "bili_user",
                        "keyword": query,
                        "page": "1",
                    },
                    headers={
                        "Accept": "application/json",
                        "Referer": "https://search.bilibili.com/",
                    },
                ) as response:
                    payload = self._read_bounded_json(response)
        except (httpx.HTTPError, OSError):
            return self._unavailable(query)
        if payload is None or payload.get("code") != 0:
            return self._unavailable(query)
        data = payload.get("data")
        rows = data.get("result") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return self._unavailable(query)

        normalized_query = query.casefold()
        all_candidates: list[dict[str, Any]] = []
        seen_uids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            uid = _positive_uid(row.get("mid"))
            name = _plain_name(row.get("uname"))
            if uid is None or name is None or uid in seen_uids:
                continue
            seen_uids.add(uid)
            all_candidates.append(
                {
                    "uid": uid,
                    "name": name,
                    "profile_url": f"https://space.bilibili.com/{uid}",
                    "exact_name_match": name.casefold() == normalized_query,
                    "_avatar_url": _avatar_url(row.get("upic")),
                }
            )

        candidates = all_candidates[:limit]
        exact_matches = [
            candidate
            for candidate in all_candidates
            if candidate["exact_name_match"]
        ]
        resolved_user = (
            {
                key: exact_matches[0][key]
                for key in ("uid", "name", "profile_url")
            }
            if len(exact_matches) == 1
            else None
        )
        try:
            upstream_total = int(data.get("numResults", len(all_candidates)))
        except (TypeError, ValueError):
            upstream_total = len(all_candidates)
        availability = "available" if all_candidates else "empty"
        match_status = (
            "exact"
            if resolved_user is not None
            else ("candidates" if all_candidates else "not_found")
        )
        return {
            "schema_version": 1,
            "query": query,
            "availability": availability,
            "match_status": match_status,
            "resolved_user": resolved_user,
            "candidates": candidates,
            "returned": len(candidates),
            "truncated": max(upstream_total, len(all_candidates)) > len(candidates),
            "data_trust": "untrusted_public_metadata",
            "error_code": None,
        }

    def _search_internal(self, normalized_query: str) -> dict[str, Any]:
        cache_key = normalized_query.casefold()
        now = self._clock()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None and cached.expires_at > now:
                return copy.deepcopy(cached.result)

        result = self._request(normalized_query, MAX_BILIBILI_CANDIDATES)
        ttl = 300.0 if result["availability"] != "unavailable" else 30.0
        with self._cache_lock:
            self._cache[cache_key] = _CacheEntry(
                expires_at=now + ttl,
                result=copy.deepcopy(result),
            )
        return result

    @staticmethod
    def _public_result(result: dict[str, Any], limit: int) -> dict[str, Any]:
        projected = copy.deepcopy(result)
        fetched_returned = int(projected["returned"])
        projected["candidates"] = projected["candidates"][:limit]
        for candidate in projected["candidates"]:
            if isinstance(candidate, dict):
                candidate.pop("_avatar_url", None)
        projected["returned"] = len(projected["candidates"])
        projected["truncated"] = bool(
            projected["truncated"] or fetched_returned > projected["returned"]
        )
        return projected

    def search(self, *, query: str, limit: int = 5) -> dict[str, Any]:
        normalized_query = _normalize_query(query)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if not 1 <= limit <= MAX_BILIBILI_CANDIDATES:
            raise ValueError("limit is outside the supported range")
        return self._public_result(
            self._search_internal(normalized_query),
            limit,
        )

    def avatar_for_uid(self, *, query: str, uid: str) -> str | None:
        """Return one internal face candidate only after exact UID matching."""

        normalized_query = _normalize_query(query)
        expected_uid = _positive_uid(uid)
        if expected_uid is None:
            raise ValueError("uid must be a positive Bilibili UID")
        result = self._search_internal(normalized_query)
        for candidate in result.get("candidates", []):
            if (
                isinstance(candidate, dict)
                and candidate.get("uid") == expected_uid
            ):
                return str(candidate.get("_avatar_url") or "") or None
        return None
