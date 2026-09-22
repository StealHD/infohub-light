"""Consistent operator-configured networking for fixed Apify API endpoints."""
import httpx


def apify_http_client(*, timeout, transport=None):
    # Match acquisition: macOS system proxies and standard proxy environment
    # settings are honored. Public/user-supplied URL policy is unchanged.
    return httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=True)
