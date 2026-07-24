"""Network egress policy for member-controlled source URLs."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import threading
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx


MAX_PUBLIC_HTTP_RESPONSE_BYTES = 2_000_000
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SYNTHETIC_DNS_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_MAX_PUBLIC_HTTP_DNS_SECONDS = 5.0


class UnsafeNetworkTarget(ValueError):
    """A source URL can reach a non-public network or contains unsafe data."""

    retryable = False


@dataclass(frozen=True, slots=True)
class ResolvedHttpTarget:
    """One validated URL hop and the exact addresses it may connect to."""

    url: str
    hostname: str
    port: int
    explicit_port: bool
    addresses: tuple[str, ...]

    @property
    def host_header(self) -> str:
        try:
            host_ip = ipaddress.ip_address(self.hostname)
        except ValueError:
            authority = self.hostname
        else:
            authority = f"[{self.hostname}]" if host_ip.version == 6 else self.hostname
        return f"{authority}:{self.port}" if self.explicit_port else authority

    def pinned_url(self, address: str) -> str:
        parsed = urlparse(self.url)
        address_ip = ipaddress.ip_address(address)
        authority = f"[{address}]" if address_ip.version == 6 else address
        if self.explicit_port:
            authority = f"{authority}:{self.port}"
        return parsed._replace(netloc=authority, fragment="").geturl()


def _host_matches_suffixes(host: str, suffixes: tuple[str, ...]) -> bool:
    normalized_host = host.lower().rstrip(".")
    return any(
        normalized_host == suffix
        or normalized_host.endswith(f".{suffix}")
        for raw_suffix in suffixes
        if (suffix := raw_suffix.lower().strip().lstrip(".").rstrip("."))
    )


def resolve_public_http_url(
    url: str,
    *,
    synthetic_dns_host_suffixes: tuple[str, ...] = (),
    allow_private_host_allowlist: bool = True,
) -> ResolvedHttpTarget:
    """Resolve one HTTP(S) hop and return only addresses approved for connection."""
    value = str(url or "").strip()
    if "${" in value:
        raise UnsafeNetworkTarget("member-controlled source URLs cannot contain environment-variable placeholders")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeNetworkTarget("source URL must be an http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeNetworkTarget("source URL credentials are not allowed")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeNetworkTarget(
            "source hostname is not a valid DNS name"
        ) from exc
    if not host:
        raise UnsafeNetworkTarget("source hostname is not a valid DNS name")
    allowlisted_hosts = {
        entry.strip().lower().rstrip(".")
        for entry in os.getenv("HORIZON_MEMBER_RSS_HOST_ALLOWLIST", "").split(",")
        if entry.strip()
    }
    try:
        explicit_port = parsed.port is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeNetworkTarget("source URL port is invalid") from exc
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
        addresses = (literal,)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeNetworkTarget("source hostname could not be resolved to a public network address") from exc
        addresses = tuple(
            dict.fromkeys(
                ipaddress.ip_address(str(entry[4][0]).split("%", 1)[0])
                for entry in resolved
            )
        )
    if not addresses:
        raise UnsafeNetworkTarget("source hostname could not be resolved to a public network address")
    if not allow_private_host_allowlist or host.lower() not in allowlisted_hosts:
        non_public = tuple(address for address in addresses if not address.is_global)
        synthetic_dns_allowed = (
            bool(non_public)
            and _host_matches_suffixes(host, synthetic_dns_host_suffixes)
            and all(address in _SYNTHETIC_DNS_NETWORK for address in non_public)
        )
        if non_public and not synthetic_dns_allowed:
            raise UnsafeNetworkTarget("member-controlled source URL must resolve only to the public network")
    return ResolvedHttpTarget(
        url=value,
        hostname=host,
        port=port,
        explicit_port=explicit_port,
        addresses=tuple(str(address) for address in addresses),
    )


def require_public_http_url(url: str) -> str:
    """Require a safe member-controlled URL without performing the request."""
    return resolve_public_http_url(url).url


async def _resolve_public_http_url_daemon(
    url: str,
    *,
    timeout: float,
    allow_private_host_allowlist: bool,
) -> ResolvedHttpTarget:
    """Resolve without tying event-loop shutdown to a blocking system resolver."""

    loop = asyncio.get_running_loop()
    future: asyncio.Future[ResolvedHttpTarget] = loop.create_future()

    def resolve() -> None:
        try:
            target = resolve_public_http_url(
                url,
                allow_private_host_allowlist=allow_private_host_allowlist,
            )
        except Exception as exc:
            outcome: tuple[ResolvedHttpTarget | None, Exception | None] = (
                None,
                exc,
            )
        else:
            outcome = (target, None)

        def publish() -> None:
            if future.done():
                return
            target_result, error = outcome
            if error is not None:
                future.set_exception(error)
            elif target_result is not None:
                future.set_result(target_result)

        try:
            loop.call_soon_threadsafe(publish)
        except RuntimeError:
            # The bounded caller already returned and closed its event loop.
            return

    threading.Thread(
        target=resolve,
        name="public-http-resolver",
        daemon=True,
    ).start()
    try:
        return await asyncio.wait_for(
            future,
            timeout=max(
                0.001,
                min(float(timeout), _MAX_PUBLIC_HTTP_DNS_SECONDS),
            ),
        )
    except TimeoutError as exc:
        raise UnsafeNetworkTarget(
            "source hostname resolution timed out"
        ) from exc


async def _request_pinned_address(
    target: ResolvedHttpTarget,
    address: str,
    *,
    headers: dict[str, str] | None,
    timeout: float,
    max_response_bytes: int,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None,
    method: str = "GET",
    content: bytes | None = None,
    read_response_body: bool = True,
) -> httpx.Response:
    request_headers = {
        key: value
        for key, value in (headers or {}).items()
        if key.lower() not in {"host", "accept-encoding"}
    }
    request_headers["Host"] = target.host_header
    request_headers["Accept-Encoding"] = "identity"
    client_options: dict[str, object] = {
        "timeout": timeout,
        "trust_env": False,
    }
    if transport_factory is not None:
        client_options["transport"] = transport_factory()
    async with httpx.AsyncClient(**client_options) as client:
        async with client.stream(
            method,
            target.pinned_url(address),
            headers=request_headers,
            content=content,
            follow_redirects=False,
            extensions={"sni_hostname": target.hostname},
        ) as response:
            content = bytearray()
            successful_response = (
                response.status_code not in _REDIRECT_STATUSES
                and response.status_code < 400
            )
            if read_response_body and successful_response:
                content_encoding = (
                    response.headers.get("content-encoding", "")
                    .strip()
                    .lower()
                )
                if content_encoding not in {"", "identity"}:
                    raise UnsafeNetworkTarget(
                        "source response content encoding is not allowed"
                    )
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = 0
                    if declared_length > max_response_bytes:
                        raise UnsafeNetworkTarget(
                            f"source response exceeded the {max_response_bytes}-byte limit"
                        )
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    if len(content) + len(chunk) > max_response_bytes:
                        raise UnsafeNetworkTarget(
                            f"source response exceeded the {max_response_bytes}-byte limit"
                        )
                    content.extend(chunk)
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
                extensions=dict(response.extensions),
            )


async def _fetch_public_http(
    url: str,
    *,
    headers: dict[str, str] | None,
    timeout: float,
    max_redirects: int,
    max_response_bytes: int,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None,
    synthetic_dns_host_suffixes: tuple[str, ...],
) -> httpx.Response:
    current_url = str(url)
    for redirect_count in range(max_redirects + 1):
        target = await asyncio.to_thread(
            resolve_public_http_url,
            current_url,
            synthetic_dns_host_suffixes=synthetic_dns_host_suffixes,
        )
        response: httpx.Response | None = None
        last_error: httpx.TransportError | None = None
        for address in target.addresses:
            try:
                response = await _request_pinned_address(
                    target,
                    address,
                    headers=headers,
                    timeout=timeout,
                    max_response_bytes=max_response_bytes,
                    transport_factory=transport_factory,
                )
                break
            except httpx.TransportError as exc:
                last_error = exc
        if response is None:
            if last_error is not None:
                raise last_error
            raise UnsafeNetworkTarget("source hostname did not provide a usable public network address")
        if response.status_code not in _REDIRECT_STATUSES:
            return response
        location = response.headers.get("location")
        if not location:
            raise UnsafeNetworkTarget("source redirect did not include a location")
        if redirect_count == max_redirects:
            raise UnsafeNetworkTarget("source exceeded the redirect limit")
        current_url = urljoin(current_url, location)
    raise UnsafeNetworkTarget("source exceeded the redirect limit")


async def fetch_public_http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    max_redirects: int = 5,
    max_response_bytes: int = MAX_PUBLIC_HTTP_RESPONSE_BYTES,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    synthetic_dns_host_suffixes: tuple[str, ...] = (),
) -> httpx.Response:
    """Fetch a member-controlled URL while pinning every hop to vetted IPs."""
    return await _fetch_public_http(
        url,
        headers=headers,
        timeout=timeout,
        max_redirects=max_redirects,
        max_response_bytes=max(1, int(max_response_bytes)),
        transport_factory=transport_factory,
        synthetic_dns_host_suffixes=synthetic_dns_host_suffixes,
    )


async def post_public_http(
    url: str,
    *,
    content: bytes,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    max_response_bytes: int = 64_000,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
) -> httpx.Response:
    """POST once to a public-only URL with DNS pinning and no redirects."""

    target = await _resolve_public_http_url_daemon(
        url,
        timeout=timeout,
        allow_private_host_allowlist=False,
    )
    # A POST may have reached the first address even when its response is lost.
    # Replaying against another DNS answer would therefore duplicate a
    # non-idempotent webhook delivery.
    return await _request_pinned_address(
        target,
        target.addresses[0],
        headers=headers,
        timeout=timeout,
        max_response_bytes=max(1, int(max_response_bytes)),
        transport_factory=transport_factory,
        method="POST",
        content=bytes(content),
        read_response_body=False,
    )
