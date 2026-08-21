"""Value-free, exact-revision AI repair for a Canary output mapping."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    ManifestMappingResult,
    map_actor_output,
    parse_actor_manifest,
    summarize_json_paths,
    validate_json_pointer,
)
from .apify_actor_observed_probe import (
    map_canary_output_for_revision,
)


class OutputMappingRepairer(Protocol):
    """AI boundary: receives only schema-like paths and JSON types."""

    async def propose_output_mapping(
        self, request: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...


_REPAIRABLE_CODES = frozenset(
    {"apify_actor_contract_mismatch", "apify_actor_metadata_only"}
)
_HOSTS = {
    "youtube": ("youtube.com", "youtu.be"),
    "x": ("x.com", "twitter.com"),
    "instagram": ("instagram.com",),
}


async def map_validation_output(
    runner: Any,
    manifest: Any,
    rows: Sequence[Mapping[str, Any]],
    target: ActorTarget,
    runtime: ActorRuntime,
    revision: Any,
) -> tuple[ManifestMappingResult, dict[str, Any] | None]:
    """Map normally, asking an optional AI only after a mapping mismatch."""

    try:
        return map_canary_output_for_revision(
            manifest, rows, target, runtime, revision
        )
    except ActorManifestError as original:
        repairer = getattr(runner, "output_mapping_repairer", None)
        if (
            repairer is None
            or str(original.code) not in _REPAIRABLE_CODES
        ):
            raise
        request = output_mapping_request(rows, revision)
        if request is None:
            raise
        try:
            proposal = await repairer.propose_output_mapping(request)
            repaired = manifest_from_output_mapping(
                proposal, request=request, manifest=manifest, revision=revision
            )
            return map_actor_output(repaired, rows, target, runtime), repaired
        except Exception:
            raise original from None


def output_mapping_request(
    rows: Sequence[Mapping[str, Any]], revision: Any
) -> dict[str, Any] | None:
    """Build a bounded AI request without targets, row values, or identifiers."""

    platform = str(revision["platform"] or "").casefold()
    if platform not in _HOSTS or not rows:
        return None
    shapes: dict[str, set[str]] = {}
    for row in rows[:3]:
        if not isinstance(row, Mapping):
            return None
        for item in summarize_json_paths(row, max_depth=6, max_paths=128)["paths"]:
            path = str(item["path"])
            shapes.setdefault(path, set()).add(str(item["type"]))
    if not shapes:
        return None
    fields = _required_fields(platform)
    return {
        "task": "map_actor_output_fields_v1",
        "route": {
            "platform": platform,
            "target_type": _route_part(revision, 1),
            "capability": _route_part(revision, 2),
        },
        "required_output_fields": list(fields),
        "dataset_row_shape": [
            {"path": path, "type": _merged_type(types)}
            for path, types in sorted(shapes.items())
        ],
        "constraints": {
            "response_must_be_exact_json_object": True,
            "response_shape": {"output": {field: "RFC6901 pointer" for field in fields}},
            "only_paths_in_dataset_row_shape": True,
            "no_values_targets_urls_credentials_or_actor_identifiers": True,
        },
    }


def manifest_from_output_mapping(
    proposal: Mapping[str, Any] | None,
    *,
    request: Mapping[str, Any],
    manifest: Any,
    revision: Any,
) -> dict[str, Any]:
    """Turn one candidate-local pointer proposal into a strict Manifest v1."""

    if not isinstance(proposal, Mapping) or set(proposal) != {"output"}:
        raise ValueError("AI output mapping proposal is invalid")
    output = proposal["output"]
    if not isinstance(output, Mapping):
        raise ValueError("AI output mapping fields are invalid")
    platform = str(request["route"]["platform"])
    fields = _required_fields(platform)
    if set(output) != set(fields):
        raise ValueError("AI output mapping fields do not match the route")
    allowed = {
        str(item["path"])
        for item in request["dataset_row_shape"]
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    selected: dict[str, str] = {}
    for field in fields:
        pointer = validate_json_pointer(str(output[field]))
        if pointer not in allowed:
            raise ValueError("AI output mapping pointer is not observed")
        selected[field] = pointer
    parsed = parse_actor_manifest(manifest)
    payload = {
        "version": 1,
        "actor_id": str(revision["actor_id"]),
        "build_number": str(revision["build_number"]),
        "input": dict(parsed.input_template),
        "output": {
            field: {
                "pointers": [pointer],
                "transforms": [_transform_for(field)],
            }
            for field, pointer in selected.items()
        },
        "semantics": {
            "identity": _identity_for(platform),
            "url_host_allowlist": list(_HOSTS[platform]),
            "empty_result_markers": [],
        },
    }
    return parse_actor_manifest(payload).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )


def _required_fields(platform: str) -> tuple[str, ...]:
    return (
        ("native_id", "url", "published_at", "title", "source_native_id")
        if platform == "youtube"
        else ("native_id", "url", "published_at", "text", "author_handle")
    )


def _identity_for(platform: str) -> dict[str, str]:
    return (
        {
            "output_field": "source_native_id",
            "target_ref": "target.native_id",
            "match": "exact",
        }
        if platform == "youtube"
        else {
            "output_field": "author_handle",
            "target_ref": "target.handle",
            "match": "handle",
        }
    )


def _transform_for(field: str) -> str:
    return {
        "native_id": "to_string",
        "url": "normalize_url",
        "published_at": "parse_datetime",
        "title": "to_string",
        "text": "strip_html",
        "source_native_id": "to_string",
        "author_handle": "to_string",
    }[field]


def _route_part(revision: Any, index: int) -> str:
    parts = str(revision["route_key"] or "").split("/")
    return parts[index] if len(parts) > index else ""


def _merged_type(types: set[str]) -> str:
    return next(iter(types)) if len(types) == 1 else "mixed"


__all__ = [
    "OutputMappingRepairer",
    "manifest_from_output_mapping",
    "map_validation_output",
    "output_mapping_request",
]
