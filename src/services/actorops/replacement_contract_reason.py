"""Safe public reasons for local replacement contract rejection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..apify_actor_manifest import parse_actor_manifest


_TARGET_ERRORS = {
    "target.native_id": "actorops_replacement_target_native_id_missing",
    "target.handle": "actorops_replacement_target_handle_missing",
    "target.canonical_url": "actorops_replacement_target_url_missing",
}


def target_context_error_code(manifest_json: str, target: Any) -> str | None:
    """Name the first safe target field required but unavailable locally."""

    template = parse_actor_manifest(manifest_json).input_template
    references = frozenset(_references(template))
    values = {
        "target.native_id": getattr(target, "native_id", None),
        "target.handle": getattr(target, "handle", None),
        "target.canonical_url": getattr(target, "canonical_url", None),
    }
    for reference, error_code in _TARGET_ERRORS.items():
        if reference in references and not values[reference]:
            return error_code
    return None


def manifest_contract_error_code(code: str) -> str:
    """Map internal Manifest failures to a bounded public explanation."""

    if code == "apify_manifest_reference_unavailable":
        return "actorops_replacement_target_context_missing"
    if code in {
        "apify_manifest_invalid",
        "apify_manifest_invalid_json",
        "apify_manifest_reference_invalid",
        "apify_manifest_too_large",
    }:
        return "actorops_replacement_manifest_invalid"
    return "actorops_replacement_input_contract_invalid"


def output_contract_error_code(code: str) -> str:
    """Keep paid-output failures specific without exposing upstream text."""

    return {
        "apify_actor_published_at_invalid": "actorops_replacement_published_at_invalid",
        "apify_actor_target_identity_mismatch": "actorops_replacement_target_identity_mismatch",
        "apify_actor_output_url_invalid": "actorops_replacement_output_url_invalid",
        "apify_actor_output_host_disallowed": "actorops_replacement_output_url_invalid",
        "apify_actor_output_outside_window": "actorops_replacement_output_outside_window",
        "apify_actor_nested_extraction_failed": "actorops_replacement_nested_extraction_failed",
        "apify_actor_mixed_rows_unclassified": "actorops_replacement_mixed_rows_unclassified",
        "apify_actor_dataset_expansion_overflow": "actorops_replacement_dataset_expansion_overflow",
    }.get(code, "actorops_replacement_contract_mismatch")


def _references(value: Any):
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str):
            yield reference
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _references(child)


__all__ = [
    "manifest_contract_error_code",
    "output_contract_error_code",
    "target_context_error_code",
]
