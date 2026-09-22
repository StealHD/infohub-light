"""Canonical contributor facts and platform-owned membership policy."""
import re
from .structured_paths import collection_at, value_at, StructureError

_HANDLE = re.compile(r'^[A-Za-z0-9_.]{1,64}$')


def normalized_handle(value):
    if not isinstance(value, str):
        return None
    clean = value.strip().lstrip('@')
    return clean.casefold() if _HANDLE.fullmatch(clean) else None


def contributors(row, structures):
    mapping = structures.contributors if structures else None
    if mapping is None:
        return ()
    result = []
    for node in collection_at(row, mapping.collection, limit=16):
        handle = value_at(node, mapping.handle)
        if normalized_handle(handle) is None:
            raise StructureError('invalid contributor identity')
        name, avatar = value_at(node, mapping.name), value_at(node, mapping.avatar_url)
        result.append({'role': mapping.role, 'handle': handle,
                       'name': name if isinstance(name, str) else None,
                       'avatar_url': safe_image_url(avatar)})
    return tuple(result)


def confirms_target(row, structures, target, semantics):
    # Relationship acceptance is route policy, not a vendor field-name heuristic.
    if (structures is None or structures.contributors is None
            or 'instagram.com' not in semantics.url_host_allowlist
            or semantics.identity.target_ref != 'target.handle'
            or semantics.identity.match != 'handle'):
        return False
    try:
        expected = normalized_handle(target.handle)
        return expected is not None and any(
            normalized_handle(value['handle']) == expected
            for value in contributors(row, structures)
        )
    except StructureError:
        return False


def safe_image_url(value):
    from urllib.parse import urlsplit
    from ..apify_actor_manifest import normalize_http_url
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = normalize_http_url(value)
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.path.lower().endswith(
                ('.mp4', '.mov', '.webm', '.m3u8', '.mp3')):
            return None
        return url
    except ValueError:
        return None
