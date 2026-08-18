"""Promote a bounded YouTube output observation into an immutable manifest."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dateutil.parser import isoparse

from .apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    ManifestMappingResult,
    MappedActorItem,
    map_actor_output,
    parse_actor_manifest,
)


_OBSERVED_POINTER_PREFIX = "/__probe_"
_YOUTUBE_HOSTS = frozenset({"youtube.com", "youtu.be"})


@dataclass(frozen=True, slots=True)
class ObservedProbeMapping:
    """A value-free Manifest derived from one validated Dataset sample."""

    result: ManifestMappingResult
    manifest: dict[str, Any]


def is_youtube_observation_probe(
    *,
    platform: str,
    target_type: str,
    capability: str,
    manifest: Mapping[str, Any] | str,
    security_evidence: Any,
) -> bool:
    """Allow only the old placeholder contract to take the observed path."""

    if (platform, target_type, capability) != ("youtube", "channel", "items"):
        return False
    evidence = (
        dict(security_evidence)
        if isinstance(security_evidence, Mapping)
        else _safe_object(security_evidence)
    )
    if evidence.get("exact_successful_build") is not True or evidence.get("input_validation") is not True:
        return False
    try:
        parsed = parse_actor_manifest(manifest)
    except ActorManifestError:
        return False
    input_json = json.dumps(parsed.input_template, sort_keys=True)
    pointers = [
        pointer
        for mapping in parsed.output._mapping_values()
        for pointer in mapping.pointers
    ]
    return (
        "target.canonical_url" in input_json
        and bool(pointers)
        and all(pointer.startswith(_OBSERVED_POINTER_PREFIX) for pointer in pointers)
    )


def can_observe_youtube_probe(
    *,
    platform: str,
    target_type: str,
    capability: str,
    manifest: Mapping[str, Any] | str,
    security_evidence: Any,
) -> bool:
    """Return whether one placeholder Build may establish a real contract."""

    return is_youtube_observation_probe(
        platform=platform,
        target_type=target_type,
        capability=capability,
        manifest=manifest,
        security_evidence=security_evidence,
    )


def map_canary_output(
    manifest: Mapping[str, Any] | str,
    rows: Sequence[Mapping[str, Any]],
    target: ActorTarget,
    runtime: ActorRuntime,
    *,
    platform: str,
    target_type: str,
    capability: str,
    security_evidence: Any,
) -> tuple[ManifestMappingResult, dict[str, Any] | None]:
    """Map normal contracts or safely learn an observed YouTube contract."""

    if not can_observe_youtube_probe(
        platform=platform,
        target_type=target_type,
        capability=capability,
        manifest=manifest,
        security_evidence=security_evidence,
    ):
        return map_actor_output(manifest, rows, target, runtime), None
    observed = _observe_youtube_rows(rows, target, runtime)
    return observed.result, observed.manifest


def map_canary_output_for_revision(
    manifest: Any,
    rows: Sequence[Mapping[str, Any]],
    target: ActorTarget,
    runtime: ActorRuntime,
    revision: Any,
) -> tuple[ManifestMappingResult, dict[str, Any] | None]:
    """Map a Canary result using only that Route's own adapter contract."""

    route_parts = str(revision["route_key"]).split("/")
    mapped, draft = map_canary_output(
        manifest, rows, target, runtime,
        platform=str(revision["platform"]),
        target_type=route_parts[1] if len(route_parts) > 1 else "",
        capability=route_parts[2] if len(route_parts) > 2 else "items",
        security_evidence=revision["security_evidence_json"],
    )
    if draft is None:
        return mapped, None
    return mapped, observed_manifest_with_identity(
        draft, actor_id=str(revision["actor_id"]),
        build_number=str(revision["build_number"]),
        input_template=manifest.input_template,
    )


def promote_observed_youtube_revision(
    ops: Any,
    *,
    validation_id: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically replace a probe's references with its observed Build contract."""

    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with ops._write() as connection:
        row = connection.execute(
            """
            SELECT validation.workspace_id, validation.route_id,
                   validation.discovery_run_id, validation.revision_id,
                   revision.candidate_id, revision.actor_id, revision.publisher,
                   revision.build_id, revision.build_number,
                   revision.input_schema_hash, revision.output_schema_hash,
                   revision.pricing_json, revision.permission_level,
                   revision.security_evidence_json
            FROM apify_actor_validations AS validation
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = validation.workspace_id
             AND revision.revision_id = validation.revision_id
            WHERE validation.workspace_id = ? AND validation.validation_id = ?
              AND validation.status = 'succeeded' AND validation.cost_final = 1
            """,
            (ops.workspace_id, validation_id),
        ).fetchone()
        if row is None:
            raise ValueError("observed probe validation is not settled")
        revision_id = "apify-revision-" + hashlib.sha256(
            "\x1f".join(
                (
                    ops.workspace_id,
                    str(row["candidate_id"]),
                    str(row["build_id"]),
                    str(row["build_number"]),
                    manifest_hash,
                )
            ).encode("utf-8")
        ).hexdigest()[:32]
        evidence = _safe_object(row["security_evidence_json"])
        evidence.update(
            {
                "observed_manifest": True,
                "observed_output_contract": True,
                "output_schema_proves_items": True,
                "probe_only": False,
            }
        )
        now = ops._now_iso()
        connection.execute(
            """
            INSERT OR IGNORE INTO apify_actor_adapter_revisions (
                revision_id, workspace_id, candidate_id, actor_id, publisher,
                build_id, build_number, manifest_json, manifest_hash,
                input_schema_hash, output_schema_hash, execution_mode,
                observed_manifest, pricing_json, permission_level,
                security_evidence_json, lifecycle, ai_provider, ai_model,
                prompt_version, discovery_run_id, canary_passed_at, created_at,
                superseded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pinned', 1, ?, ?, ?,
                'probationary', NULL, NULL, 'observed_youtube_probe_v1', ?, ?, ?, NULL)
            """,
            (
                revision_id,
                ops.workspace_id,
                str(row["candidate_id"]),
                str(row["actor_id"]),
                str(row["publisher"]),
                str(row["build_id"]),
                str(row["build_number"]),
                canonical,
                manifest_hash,
                row["input_schema_hash"],
                row["output_schema_hash"],
                row["pricing_json"],
                str(row["permission_level"]),
                json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                row["discovery_run_id"],
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO apify_actor_discovery_run_revisions (
                workspace_id, run_id, revision_id, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (ops.workspace_id, str(row["discovery_run_id"]), revision_id, now),
        )
        connection.execute(
            """UPDATE apify_actor_validations SET revision_id = ?
               WHERE workspace_id = ? AND validation_id = ?""",
            (revision_id, ops.workspace_id, validation_id),
        )
        connection.execute(
            """UPDATE apify_actor_canary_batch_items SET revision_id = ?
               WHERE workspace_id = ? AND validation_id = ?""",
            (revision_id, ops.workspace_id, validation_id),
        )
        connection.execute(
            """UPDATE apify_actor_candidates
               SET state = 'probationary', last_error_code = NULL,
                   last_success_at = ?, success_count = success_count + 1,
                   updated_at = ?
               WHERE workspace_id = ? AND id = ?""",
            (now, now, ops.workspace_id, str(row["candidate_id"])),
        )
    return ops.get_validation(validation_id)


def settled_observed_validation(
    ops: Any, validation: Mapping[str, Any], validation_id: str, manifest: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """Return the settled validation, promoting an observed contract when present."""

    return (
        promote_observed_youtube_revision(ops, validation_id=validation_id, manifest=manifest)
        if manifest is not None else validation
    )


def _observe_youtube_rows(
    rows: Sequence[Mapping[str, Any]], target: ActorTarget, runtime: ActorRuntime) -> ObservedProbeMapping:
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence) or not rows:
        raise ActorManifestError("apify_actor_contract_mismatch", "Actor Dataset has no observable content rows")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ActorManifestError("apify_actor_contract_mismatch", "Actor Dataset contains a non-object row")
        pointers = _scalar_paths(row)
        observed = _observe_youtube_row(pointers, target)
        if observed is None:
            continue
        item, selected = observed
        manifest = _observed_manifest(
            actor_id="", build_number="", input_template={}, selected=selected
        )
        # The caller fills immutable Actor/Build/input facts from its prior
        # revision; only values proven by this row become output pointers.
        return ObservedProbeMapping(
            result=ManifestMappingResult((item,), "valid_nonempty", latest_published_at=item.published_at.isoformat(), latest_native_id=item.native_id),
            manifest=manifest,
        )
    raise ActorManifestError("apify_actor_contract_mismatch", "Actor output did not prove a matching YouTube content item")


def observed_manifest_with_identity(
    manifest: Mapping[str, Any], *, actor_id: str, build_number: str, input_template: Mapping[str, Any]
) -> dict[str, Any]:
    """Attach immutable revision facts after the value-free observation."""

    payload = dict(manifest)
    payload["actor_id"] = actor_id
    payload["build_number"] = build_number
    payload["input"] = dict(input_template)
    parse_actor_manifest(payload)
    return payload


def _observe_youtube_row(
    paths: Mapping[str, Any], target: ActorTarget
) -> tuple[MappedActorItem, dict[str, str]] | None:
    url_path, url = _pick(paths, ("videourl", "url", "link"), _youtube_url)
    native_path, native = _pick(paths, ("videoid", "id"), _video_id)
    if native is None:
        native = _video_id(url)
        native_path = url_path
    published_path, published = _pick(paths, ("publishedat", "publisheddate", "uploaddate", "date", "timestamp"), _datetime)
    title_path, title = _pick(paths, ("videotitle", "title", "name"), _text)
    source_path, source = _pick(paths, ("channelid", "sourceid", "authorid"), _text)
    if not all((url_path, url, native_path, native, published_path, published, title_path, title, source_path, source)):
        return None
    if _video_id(url) != native:
        return None
    if str(source) != str(target.native_id or ""):
        return None
    try:
        item = MappedActorItem(
            native_id=str(native), url=str(url), published_at=published,
            title=str(title), source_native_id=str(source),
        )
    except ValueError:
        return None
    return item, {
        "native_id": str(native_path), "url": str(url_path),
        "published_at": str(published_path), "title": str(title_path),
        "source_native_id": str(source_path),
    }


def _observed_manifest(*, actor_id: str, build_number: str, input_template: Mapping[str, Any], selected: Mapping[str, str]) -> dict[str, Any]:
    transforms = {
        "native_id": ["to_string"], "url": ["normalize_url"],
        "published_at": ["parse_datetime"], "title": ["to_string"],
        "source_native_id": ["to_string"],
    }
    return {
        "version": 1, "actor_id": actor_id, "build_number": build_number,
        "input": dict(input_template),
        "output": {
            key: {"pointers": [pointer], "transforms": transforms[key]}
            for key, pointer in selected.items()
        },
        "semantics": {
            "identity": {"output_field": "source_native_id", "target_ref": "target.native_id", "match": "exact"},
            "url_host_allowlist": ["youtube.com", "youtu.be"],
            "empty_result_markers": [],
        },
    }


def _scalar_paths(value: Mapping[str, Any], *, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    if depth > 4:
        return {}
    result: dict[str, Any] = {}
    for key, child in value.items():
        if not isinstance(key, str):
            continue
        pointer = f"{prefix}/{key.replace('~', '~0').replace('/', '~1')}"
        if isinstance(child, Mapping):
            result.update(_scalar_paths(child, prefix=pointer, depth=depth + 1))
        elif isinstance(child, (str, int, float)) and not isinstance(child, bool):
            result[pointer] = child
    return result


def _pick(paths: Mapping[str, Any], names: tuple[str, ...], validator: Any) -> tuple[str | None, Any | None]:
    for name in names:
        for pointer, value in paths.items():
            normalized = pointer.rsplit("/", 1)[-1].replace("_", "").replace("-", "").casefold()
            if normalized != name:
                continue
            converted = validator(value)
            if converted is not None:
                return pointer, converted
    return None, None


def _youtube_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    host = parsed.hostname.casefold().removeprefix("www.") if parsed.hostname else ""
    normalized = value.strip()
    return normalized if host in _YOUTUBE_HOSTS and _video_id(normalized) else None


def _video_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.hostname:
        query = parse_qs(parsed.query).get("v", [])
        if query and query[0]:
            return query[0]
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[-2] in {"shorts", "live"}:
            return parts[-1]
        return None
    return value.strip() if len(value.strip()) <= 512 else None


def _datetime(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = float(value)
            if abs(timestamp) > 4_102_444_800:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        parsed = isoparse(str(value))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _safe_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


__all__ = [
    "can_observe_youtube_probe",
    "is_youtube_observation_probe",
    "map_canary_output",
    "map_canary_output_for_revision",
    "observed_manifest_with_identity",
    "promote_observed_youtube_revision",
    "settled_observed_validation",
]
