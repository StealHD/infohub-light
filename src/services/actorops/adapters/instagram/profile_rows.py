"""Bounded Instagram collaboration-row normalization for identity validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ....apify_actor_manifest import (
    ActorManifestError,
    MAX_DATASET_ROWS,
    normalize_http_url,
    parse_actor_manifest,
    resolve_json_pointer,
)
from ...ports import ActorManifest, TargetSpec
from ...presentation_evidence import PreparedPresentationRow
from ...presentation_row_paths import avatar_alias_rank, normalized_key
from .common import normalize_profile_target


_MAX_COAUTHORS = 16
_MAX_ROW_FIELDS = 512
_MAX_IDENTITY_FIELDS = 64
_MAX_PROFILE_KEYS = 512
_MAX_PROFILE_DEPTH = 8
_IDENTITY_CONTAINERS = frozenset({"user", "owner"})
_AVATAR_ALIAS_RANK = avatar_alias_rank("instagram")
_SCRUBBED_PROFILE_KEYS = frozenset(
    {*_AVATAR_ALIAS_RANK, "profilepicid"}
)
_MISSING = object()


def prepare_profile_rows(
    rows: Sequence[Mapping[str, object]],
    target: TargetSpec,
    manifest: ActorManifest,
) -> Sequence[Mapping[str, object]]:
    """Return selective copies only when exact coauthor evidence repairs identity."""

    if len(rows) > MAX_DATASET_ROWS:
        return rows
    expected = _normalized_username(target.handle)
    if expected is None:
        return rows
    parsed = parse_actor_manifest(manifest.manifest_json)
    rule = parsed.semantics.identity
    if rule.target_ref != "target.handle" or rule.match != "handle":
        return rows
    mapping = getattr(parsed.output, rule.output_field)
    avatar_mapping = parsed.output.author_avatar_url
    avatar_pointers = avatar_mapping.pointers if avatar_mapping is not None else ()
    prepared: list[Mapping[str, object]] = []
    changed = False
    for row in rows:
        current = _prepare_row(
            row, mapping.pointers, avatar_pointers, target.handle, expected
        )
        changed = changed or current is not row
        prepared.append(current)
    return tuple(prepared) if changed else rows


def _prepare_row(
    row: Mapping[str, object],
    pointers: Sequence[str],
    avatar_pointers: Sequence[str],
    target_handle: str | None,
    expected: str,
) -> Mapping[str, object]:
    selected = _selected_identity(row, pointers)
    if selected is None:
        return row
    pointer, value = selected
    actual = _normalized_username(value)
    container_key = _identity_container(pointer)
    if actual is None and container_key is not None:
        raise ActorManifestError(
            "apify_actor_target_identity_mismatch",
            "Instagram owner identity is invalid",
            retryable=True,
        )
    if actual is None or actual == expected:
        return row
    coauthor = _exact_coauthor(row, expected)
    if container_key is None or coauthor is None:
        return row
    container = row.get(container_key)
    if not isinstance(container, Mapping) or not target_handle:
        return row
    containers = {
        key: value
        for key in _IDENTITY_CONTAINERS
        if isinstance((value := row.get(key)), Mapping)
    }
    if (
        len(row) > _MAX_ROW_FIELDS
        or any(len(value) > _MAX_IDENTITY_FIELDS for value in containers.values())
    ):
        return row
    prepared = dict(row)
    for key, value in containers.items():
        synthetic = _scrub_profile_mapping(value)
        if synthetic is None:
            return row
        _scrub_manifest_avatar_path(synthetic, key, avatar_pointers)
        if key == container_key:
            synthetic["username"] = target_handle
        prepared[key] = synthetic
    avatar_hint = _coauthor_avatar(coauthor)
    return (
        PreparedPresentationRow(prepared, avatar_hint)
        if avatar_hint is not None
        else prepared
    )


def _selected_identity(
    row: Mapping[str, object], pointers: Sequence[str]
) -> tuple[str, object] | None:
    for pointer in pointers:
        value = resolve_json_pointer(row, pointer, default=_MISSING)
        if value is _MISSING or value is None:
            continue
        if not isinstance(value, str) or value.strip():
            return pointer, value
    return None


def _identity_container(pointer: str) -> str | None:
    tokens = [
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer.split("/")[1:]
    ]
    if (
        len(tokens) == 2
        and tokens[0] in _IDENTITY_CONTAINERS
        and tokens[1] == "username"
    ):
        return tokens[0]
    return None


def _exact_coauthor(
    row: Mapping[str, object], expected: str
) -> Mapping[str, object] | None:
    values = row.get("coauthor_producers")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return None
    return next(
        (
            value
            for value in values[:_MAX_COAUTHORS]
            if isinstance(value, Mapping)
            and _normalized_username(value.get("username")) == expected
        ),
        None,
    )


def _coauthor_avatar(coauthor: Mapping[str, object]) -> str | None:
    if len(coauthor) > _MAX_IDENTITY_FIELDS:
        return None
    candidates = sorted(
        (
            (rank, value)
            for key, value in coauthor.items()
            if isinstance(key, str)
            and isinstance(value, str)
            and (rank := _AVATAR_ALIAS_RANK.get(normalized_key(key)))
            is not None
        ),
        key=lambda value: value[0],
    )
    for _rank, value in candidates:
        try:
            return normalize_http_url(value)
        except ValueError:
            continue
    return None


def _scrub_profile_mapping(
    value: Mapping[object, object],
) -> dict[object, object] | None:
    key_count = 0
    seen: set[int] = set()

    def scrub(node: Mapping[object, object], depth: int) -> dict[object, object] | None:
        nonlocal key_count
        marker = id(node)
        if marker in seen or depth > _MAX_PROFILE_DEPTH:
            return None
        seen.add(marker)
        result: dict[object, object] = {}
        for key, child in node.items():
            key_count += 1
            if key_count > _MAX_PROFILE_KEYS:
                return None
            if isinstance(key, str) and normalized_key(key) in _SCRUBBED_PROFILE_KEYS:
                continue
            if isinstance(child, Mapping):
                cleaned = scrub(child, depth + 1)
                if cleaned is None:
                    return None
                result[key] = cleaned
            else:
                result[key] = child
        seen.remove(marker)
        return result

    return scrub(value, 0)


def _scrub_manifest_avatar_path(
    container: dict[str, object],
    container_key: str,
    pointers: Sequence[str],
) -> None:
    for pointer in pointers:
        tokens = [
            value.replace("~1", "/").replace("~0", "~")
            for value in pointer.split("/")[1:]
        ]
        if len(tokens) < 2 or tokens[0] != container_key:
            continue
        current: object = container
        for token in tokens[1:-1]:
            if not isinstance(current, dict):
                break
            current = current.get(token)
        else:
            if isinstance(current, dict):
                current.pop(tokens[-1], None)


def _normalized_username(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        normalized = normalize_profile_target(value).handle
    except ValueError:
        return None
    return str(normalized or "").casefold() or None


__all__ = ["prepare_profile_rows"]
