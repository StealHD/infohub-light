"""Pure content identity shared by Feed projection and offline migrations."""
import hashlib
from typing import Any
from urllib.parse import urlsplit


def canonical_url_key(url: Any) -> str:
    """Normalize URL identity while preserving the complete query string."""
    parsed = urlsplit(str(url or ''))
    hostname = (parsed.hostname or '').lower()
    if hostname.startswith('www.'):
        hostname = hostname[4:]
    port = f':{parsed.port}' if parsed.port else ''
    path = parsed.path.rstrip('/')
    query = f'?{parsed.query}' if parsed.query else ''
    return f'{hostname}{port}{path}{query}'


def feed_item_identity(item: dict[str, Any]) -> str:
    url = item.get('url')
    return f'url:{canonical_url_key(url)}' if url else f"id:{item.get('id') or ''}"


def feed_item_fingerprint(item: dict[str, Any]) -> str:
    try:
        identity = feed_item_identity(item)
    except ValueError:
        # Malformed historical URLs still retain their stable article ID.
        identity = f"id:{item.get('id') or ''}"
    return hashlib.sha256(identity.encode()).hexdigest()
