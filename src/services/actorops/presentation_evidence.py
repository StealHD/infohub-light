"""Bounded target-bound presentation evidence for validated Actor rows."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from ..apify_actor_manifest import (
    ActorRuntime,
    ActorTarget,
    MAX_DATASET_ROWS,
    map_actor_output,
    normalize_http_url,
    parse_actor_manifest,
    resolve_json_pointer,
)
from .ports import ActorManifest, PresentationEvidence, TargetSpec
from .presentation_row_paths import (
    PRESENTATION_AVATAR_FALLBACK_POINTER,
    avatar_alias_rank,
    avatar_candidates,
    normalized_key,
)


_MAX_EVIDENCE_ROWS = 20
_MAX_EVIDENCE_KEYS = 512
_MAX_EVIDENCE_DEPTH = 4
_SAFE_DESCENDANTS = frozenset({"profile", "account"})
_HINT_PATH = ("__actorops_target", "avatar_url")


class PreparedPresentationRow(Mapping[str, object]):
    """A selective row copy with a non-mapping, unspoofable avatar hint."""

    __slots__ = ("_row", "_avatar_hint")

    def __init__(self, row: Mapping[str, object], avatar_hint: str) -> None:
        self._row = row
        self._avatar_hint = normalize_http_url(avatar_hint)

    def __getitem__(self, key: str) -> object:
        return self._row[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._row)

    def __len__(self) -> int:
        return len(self._row)

    @property
    def avatar_hint(self) -> str:
        return self._avatar_hint


def validated_presentation_evidence(
    rows: Sequence[Mapping[str, object]],
    target: TargetSpec,
    manifest: ActorManifest,
    platform: str,
) -> PresentationEvidence:
    """Revalidate individual content rows, then retain only identity-bound paths."""

    parsed = parse_actor_manifest(manifest.manifest_json)
    actor_target = ActorTarget(
        canonical_url=target.canonical_url,
        native_id=target.native_id,
        handle=target.handle,
    )
    runtime = ActorRuntime(max_items=1)
    evidence_rows: list[Mapping[str, object]] = []
    content_row_count = 0
    for row in tuple(rows)[:MAX_DATASET_ROWS]:
        if content_row_count >= _MAX_EVIDENCE_ROWS:
            break
        try:
            result = map_actor_output(parsed, (row,), actor_target, runtime)
        except Exception:
            continue
        if result.semantic_outcome != "valid_nonempty":
            continue
        content_row_count += 1
        evidence = _target_bound_row(row, parsed, platform)
        if evidence:
            evidence_rows.append(evidence)
    bounded = tuple(evidence_rows)
    return PresentationEvidence(
        rows=bounded,
        avatar_url=_first_avatar_url(bounded, platform),
        content_row_count=content_row_count,
    )


def _target_bound_row(
    row: Mapping[str, object], manifest: Any, platform: str
) -> dict[str, object]:
    rule = manifest.semantics.identity
    identity_mapping = getattr(manifest.output, rule.output_field)
    identity_pointer = _selected_pointer(row, identity_mapping.pointers)
    if identity_pointer is None:
        return {}
    identity_scope = _pointer_tokens(identity_pointer)[:-1]
    paths = _alias_paths(row, identity_scope, platform)
    avatar_mapping = manifest.output.author_avatar_url
    if avatar_mapping is not None:
        avatar_pointer = _selected_pointer(row, avatar_mapping.pointers)
        if avatar_pointer is not None:
            avatar_path = _pointer_tokens(avatar_pointer)
            if _is_target_bound(identity_scope, avatar_path):
                paths.append(avatar_path)
    hint = row.avatar_hint if isinstance(row, PreparedPresentationRow) else None
    if hint is not None:
        paths.append(_HINT_PATH)
    evidence: dict[str, object] = {}
    for path in dict.fromkeys(paths):
        value = hint if path == _HINT_PATH else _resolve_tokens(row, path)
        if isinstance(value, str):
            _set_path(evidence, path, value)
    return evidence


def _alias_paths(
    row: Mapping[str, object],
    identity_scope: tuple[str, ...],
    platform: str,
) -> list[tuple[str, ...]]:
    node = _resolve_tokens(row, identity_scope)
    if not isinstance(node, Mapping):
        return []
    aliases = avatar_alias_rank(platform)
    paths: list[tuple[str, ...]] = []
    key_count = 0

    def visit(current: Mapping[str, object], path: tuple[str, ...], depth: int) -> None:
        nonlocal key_count
        for raw_key, value in current.items():
            key_count += 1
            if key_count > _MAX_EVIDENCE_KEYS:
                return
            if not isinstance(raw_key, str):
                continue
            child_path = (*path, raw_key)
            key = normalized_key(raw_key)
            if key in aliases and isinstance(value, str):
                paths.append(child_path)
            if (
                identity_scope
                and depth < _MAX_EVIDENCE_DEPTH
                and key in _SAFE_DESCENDANTS
                and isinstance(value, Mapping)
            ):
                visit(value, child_path, depth + 1)

    visit(node, identity_scope, 0)
    return paths


def _selected_pointer(
    row: Mapping[str, object], pointers: Sequence[str]
) -> str | None:
    for pointer in pointers:
        value = resolve_json_pointer(row, pointer)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        return pointer
    return None


def _is_target_bound(
    identity_scope: tuple[str, ...], avatar_path: tuple[str, ...]
) -> bool:
    if not identity_scope:
        return len(avatar_path) == 1
    if avatar_path[: len(identity_scope)] != identity_scope:
        return False
    remainder = avatar_path[len(identity_scope) :]
    return bool(remainder) and all(
        normalized_key(value) in _SAFE_DESCENDANTS for value in remainder[:-1]
    )


def _first_avatar_url(
    rows: Sequence[Mapping[str, object]], platform: str
) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    aliases = avatar_alias_rank(platform)
    for row in rows:
        candidates.extend(avatar_candidates(row, aliases))
    for _rank, _depth, pointer in sorted(set(candidates)):
        for row in rows:
            value = resolve_json_pointer(row, pointer)
            if not isinstance(value, str):
                continue
            try:
                return normalize_http_url(value)
            except ValueError:
                continue
    for row in rows:
        value = resolve_json_pointer(row, PRESENTATION_AVATAR_FALLBACK_POINTER)
        if not isinstance(value, str):
            continue
        try:
            return normalize_http_url(value)
        except ValueError:
            continue
    return None


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    return tuple(
        value.replace("~1", "/").replace("~0", "~")
        for value in pointer.split("/")[1:]
    )


def _resolve_tokens(row: object, path: tuple[str, ...]) -> object:
    current = row
    for token in path:
        if not isinstance(current, Mapping) or token not in current:
            return None
        current = current[token]
    return current


def _set_path(row: dict[str, object], path: tuple[str, ...], value: str) -> None:
    current = row
    for token in path[:-1]:
        child = current.get(token)
        if not isinstance(child, dict):
            child = {}
            current[token] = child
        current = child
    current[path[-1]] = value


__all__ = ["PreparedPresentationRow", "validated_presentation_evidence"]
