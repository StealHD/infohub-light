"""Optional bounded row preparation shared by all Actor execution paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..apify_actor_manifest import ActorManifestError, parse_actor_manifest
from ..apify_actor_row_extraction import (
    DatasetExtractionError,
    ExtractedRows,
    extract_dataset_rows,
)
from .ports import ActorManifest, TargetSpec
from .presentation_mapping import CandidatePresentationMappings


def prepare_adapter_rows(
    adapter: Any,
    rows: Sequence[Mapping[str, object]],
    target: TargetSpec,
    manifest: ActorManifest,
) -> Sequence[Mapping[str, object]]:
    del adapter, target
    return extract_rows(rows, manifest).rows


def extract_rows(
    rows: Sequence[Mapping[str, object]], manifest: ActorManifest
) -> ExtractedRows:
    try:
        parsed = parse_actor_manifest(manifest.manifest_json)
        return extract_dataset_rows(rows, parsed.row_extraction)
    except DatasetExtractionError as error:
        raise ActorManifestError(
            error.code,
            "Actor Dataset rows could not be safely extracted",
            retryable=True,
        ) from None


def validate_and_enrich_adapter_rows(
    repository: Any, adapter: Any, rows: Sequence[Mapping[str, object]],
    target: TargetSpec, manifest: ActorManifest, window: Any,
    candidate: Any, platform: str,
) -> Any:
    prepared = prepare_adapter_rows(adapter, rows, target, manifest)
    batch = adapter.validate_output(prepared, target, manifest, window)
    return CandidatePresentationMappings(repository).enrich_batch(
        candidate, platform, batch
    )


__all__ = [
    "extract_rows", "prepare_adapter_rows", "validate_and_enrich_adapter_rows",
]
