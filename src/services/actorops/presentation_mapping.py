"""Optional avatar mappings kept outside immutable execution Manifests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ..apify_actor_manifest import (
    normalize_http_url,
    parse_actor_manifest,
    resolve_json_pointer,
    validate_json_pointer,
)
from .ports import NormalizedBatch
from .presentation_row_paths import (
    PRESENTATION_AVATAR_FALLBACK_POINTER,
    avatar_alias_rank,
    avatar_candidates as _avatar_candidates,
    json_pointer as _pointer,
    normalized_key as _key,
)


_TABLE = "actor_candidate_presentation_mappings_v2"
_MAX_ROWS = 20


@dataclass(frozen=True, slots=True)
class PresentationMapping:
    status: str
    avatar_json_pointer: str | None = None
    evidence_kind: str | None = None
    generation: int = 0


class CandidatePresentationMappings:
    """Read and atomically refresh the exact Candidate revision sidecar."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def status(self, candidate: Any) -> str:
        try:
            return self.current(candidate).status
        except Exception:
            return "missing"

    def current(self, candidate: Any) -> PresentationMapping:
        if not self._available():
            return PresentationMapping("missing")
        identity = _identity(candidate)
        if identity is None:
            return PresentationMapping("stale")
        row = self.repository.connection.execute(
            f"""SELECT mapping_status, avatar_json_pointer, evidence_kind, generation
                  FROM {_TABLE} WHERE workspace_id=? AND candidate_id=?
                   AND build_id=? AND output_schema_hash=?""",
            (self.repository.workspace_id, candidate.candidate_id, *identity),
        ).fetchone()
        if row is not None:
            return PresentationMapping(
                str(row["mapping_status"]), row["avatar_json_pointer"],
                str(row["evidence_kind"]),
                int(row["generation"]),
            )
        stale = self.repository.connection.execute(
            f"SELECT 1 FROM {_TABLE} WHERE workspace_id=? AND candidate_id=? LIMIT 1",
            (self.repository.workspace_id, candidate.candidate_id),
        ).fetchone()
        return PresentationMapping("stale" if stale else "missing")

    def refresh_from_schema(
        self, candidate: Any, platform: str, output_schema: Mapping[str, object]
    ) -> PresentationMapping:
        pointer = avatar_pointer_from_schema(output_schema, platform)
        return self._upsert(candidate, pointer, evidence_kind="schema")

    def refresh_pointer(
        self,
        candidate: Any,
        pointer: str | None,
        *,
        evidence_kind: str = "schema",
    ) -> PresentationMapping:
        if evidence_kind not in {"manifest", "schema"}:
            raise ValueError("actorops presentation evidence kind is invalid")
        return self._upsert(candidate, pointer, evidence_kind=evidence_kind)

    def import_manifest(self, candidate: Any) -> PresentationMapping:
        pointer = avatar_pointer_from_manifest(candidate.manifest_json)
        if pointer is None:
            return self.current(candidate)
        return self._upsert(candidate, pointer, evidence_kind="manifest")

    def observe_success(
        self,
        candidate: Any,
        platform: str,
        rows: Sequence[Mapping[str, object]],
    ) -> PresentationMapping:
        current = self.current(candidate)
        if current.status == "ready":
            if current.avatar_json_pointer and _first_avatar_url(
                rows, current.avatar_json_pointer
            ) is not None:
                return current
            pointer = avatar_pointer_from_rows(rows, platform)
            return self._replace_invalid_ready(candidate, current, pointer)
        pointer = avatar_pointer_from_rows(rows, platform)
        return self._upsert(candidate, pointer, evidence_kind="observed")

    def enrich_batch(
        self,
        candidate: Any,
        platform: str,
        batch: NormalizedBatch,
    ) -> NormalizedBatch:
        """Observe only after core validation, then resolve an ephemeral URL."""

        evidence = batch.presentation_evidence
        if evidence is None:
            return batch
        try:
            mapping = self.current(candidate)
            if mapping.evidence_kind is None:
                mapping = self.import_manifest(candidate)
            if evidence.content_row_count:
                mapping = self.observe_success(candidate, platform, evidence.rows)
            pointer = mapping.avatar_json_pointer
            avatar_url = evidence.avatar_url
            if avatar_url is None and pointer is not None:
                avatar_url = _first_avatar_url(evidence.rows, pointer)
        except Exception:
            # Presentation evidence is optional and must never turn a valid,
            # already-paid content result into a Candidate failure.
            return batch
        if avatar_url == batch.source_avatar_url:
            return batch
        return replace(batch, source_avatar_url=avatar_url)

    def _upsert(
        self, candidate: Any, pointer: str | None, *, evidence_kind: str
    ) -> PresentationMapping:
        if not self._available():
            return PresentationMapping("missing")
        identity = _identity(candidate)
        if identity is None:
            return PresentationMapping("stale")
        if pointer is not None:
            validate_json_pointer(pointer)
        current = self.current(candidate)
        if current.status == "ready" and current.avatar_json_pointer:
            return current
        if current.status == "missing" and pointer is None:
            return current
        stamp = datetime.now(timezone.utc).isoformat()
        values = (
            self.repository.workspace_id, candidate.candidate_id, *identity,
            "ready" if pointer else "missing", pointer, evidence_kind,
            stamp, stamp,
        )
        with self.repository.transaction():
            self.repository.connection.execute(
                f"""INSERT INTO {_TABLE} (
                       workspace_id, candidate_id, build_id, output_schema_hash,
                       mapping_status, avatar_json_pointer, evidence_kind,
                       generation, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(workspace_id, candidate_id, build_id, output_schema_hash)
                   DO UPDATE SET mapping_status=excluded.mapping_status,
                       avatar_json_pointer=excluded.avatar_json_pointer,
                       evidence_kind=excluded.evidence_kind,
                       generation={_TABLE}.generation+1,
                       updated_at=excluded.updated_at
                   WHERE {_TABLE}.mapping_status != 'ready'""",
                values,
            )
        return self.current(candidate)

    def _replace_invalid_ready(
        self,
        candidate: Any,
        current: PresentationMapping,
        pointer: str | None,
    ) -> PresentationMapping:
        """CAS-repair or downgrade one ready pointer disproven by target rows."""

        identity = _identity(candidate)
        if identity is None:
            return PresentationMapping("stale")
        if pointer is not None:
            validate_json_pointer(pointer)
        stamp = datetime.now(timezone.utc).isoformat()
        with self.repository.transaction():
            self.repository.connection.execute(
                f"""UPDATE {_TABLE}
                       SET mapping_status=?, avatar_json_pointer=?,
                           evidence_kind='observed',
                           generation=generation+1, updated_at=?
                     WHERE workspace_id=? AND candidate_id=?
                       AND build_id=? AND output_schema_hash=?
                       AND mapping_status='ready' AND evidence_kind=?
                       AND generation=? AND avatar_json_pointer=?""",
                (
                    "ready" if pointer else "missing",
                    pointer,
                    stamp,
                    self.repository.workspace_id,
                    candidate.candidate_id,
                    *identity,
                    current.evidence_kind,
                    current.generation,
                    current.avatar_json_pointer,
                ),
            )
        return self.current(candidate)

    def _available(self) -> bool:
        return self.repository.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_TABLE,),
        ).fetchone() is not None


def avatar_pointer_from_manifest(manifest_json: object) -> str | None:
    try:
        manifest = parse_actor_manifest(str(manifest_json or ""))
    except Exception:
        return None
    mapping = manifest.output.author_avatar_url
    if mapping is None:
        return None
    return validate_json_pointer(mapping.pointers[0])


def avatar_pointer_from_schema(
    schema: Mapping[str, object], platform: str
) -> str | None:
    aliases = avatar_alias_rank(platform)
    candidates: list[tuple[int, int, str]] = []
    definitions = _definitions(schema)
    seen: set[tuple[int, str]] = set()

    def visit(node: object, path: tuple[str, ...], depth: int) -> None:
        if depth > 8 or not isinstance(node, Mapping):
            return
        marker = (id(node), "/".join(path))
        if marker in seen or len(seen) >= 512:
            return
        seen.add(marker)
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target = _resolve_schema_ref(definitions, ref)
            if target is not None:
                visit(target, path, depth + 1)
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            for raw_key, child in properties.items():
                if not isinstance(raw_key, str):
                    continue
                child_path = (*path, raw_key)
                rank = aliases.get(_key(raw_key))
                if rank is not None and _schema_string_like(child):
                    candidates.append((rank, len(child_path), _pointer(child_path)))
                visit(child, child_path, depth + 1)
        for keyword in ("allOf", "anyOf", "oneOf"):
            variants = node.get(keyword)
            if isinstance(variants, Sequence) and not isinstance(variants, str):
                for child in variants[:12]:
                    visit(child, path, depth + 1)

    visit(schema, (), 0)
    return min(candidates, default=(0, 0, None))[2]


def avatar_pointer_from_rows(
    rows: Sequence[Mapping[str, object]], platform: str
) -> str | None:
    aliases = avatar_alias_rank(platform)
    bounded_rows = tuple(rows)[:_MAX_ROWS]
    candidates: list[tuple[int, int, str]] = []
    for row in bounded_rows:
        candidates.extend(_avatar_candidates(row, aliases))
    for _rank, _depth, pointer in sorted(set(candidates)):
        if _first_avatar_url(bounded_rows, pointer) is not None:
            return pointer
    if _first_avatar_url(
        bounded_rows, PRESENTATION_AVATAR_FALLBACK_POINTER
    ) is not None:
        return PRESENTATION_AVATAR_FALLBACK_POINTER
    return None


def _first_avatar_url(
    rows: Sequence[Mapping[str, object]], pointer: str
) -> str | None:
    for row in tuple(rows)[:_MAX_ROWS]:
        value = resolve_json_pointer(row, pointer)
        if not isinstance(value, str):
            continue
        try:
            return normalize_http_url(value)
        except ValueError:
            continue
    return None


def _identity(candidate: Any) -> tuple[str, str] | None:
    build_id = str(getattr(candidate, "build_id", "") or "").strip()
    schema_hash = str(getattr(candidate, "output_schema_hash", "") or "").strip()
    if not build_id or len(schema_hash) != 64:
        return None
    return build_id, schema_hash


def _schema_string_like(value: object) -> bool:
    if not isinstance(value, Mapping):
        return True
    raw_type = value.get("type")
    if raw_type is None:
        return True
    if isinstance(raw_type, str):
        return raw_type == "string"
    return isinstance(raw_type, Sequence) and "string" in raw_type


def _definitions(schema: Mapping[str, object]) -> Mapping[str, object]:
    return {"$defs": schema.get("$defs", {}), "definitions": schema.get("definitions", {})}


def _resolve_schema_ref(
    definitions: Mapping[str, object], ref: str
) -> object | None:
    parts = ref[2:].split("/")
    current: object = definitions
    for part in parts:
        if not isinstance(current, Mapping):
            return None
        current = current.get(part.replace("~1", "/").replace("~0", "~"))
    return current


__all__ = [
    "CandidatePresentationMappings",
    "PresentationMapping",
    "avatar_pointer_from_manifest",
    "avatar_pointer_from_rows",
    "avatar_pointer_from_schema",
]
