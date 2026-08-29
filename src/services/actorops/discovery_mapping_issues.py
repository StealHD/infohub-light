"""Safe public vocabulary for Discovery mapping diagnostics."""

from __future__ import annotations

from .domain import CandidateRecord


_PUBLIC_CODES = {
    "actorops_discovery_ai_missing_post_author_handle": "missing_post_author_handle",
    "actorops_discovery_ai_output_not_content_items": "output_not_content_items",
    "actorops_discovery_ai_missing_target_input": "missing_target_input",
    "actorops_discovery_ai_missing_required_input_value": "missing_required_input_value",
    "actorops_discovery_ai_missing_native_id": "missing_post_id",
    "actorops_discovery_ai_missing_url": "missing_post_url",
    "actorops_discovery_ai_missing_published_at": "missing_post_published_at",
    "actorops_discovery_ai_missing_text": "missing_post_text",
    "actorops_discovery_ai_missing_identity": "missing_source_identity",
    "actorops_discovery_ai_ambiguous_output": "ambiguous_output",
    "actorops_discovery_ai_wrong_actor_type": "wrong_actor_type",
    "actorops_discovery_ai_nested_content_items": "nested_content_items",
    "actorops_discovery_ai_named_dataset_required": "named_dataset_required",
    "actorops_discovery_ai_output_schema_incomplete": "output_schema_incomplete",
    "actorops_discovery_ai_target_identity_derivable": "target_identity_derivable",
    "actorops_discovery_ai_relative_published_at": "relative_published_at",
    "actorops_discovery_ai_nested_extraction_failed": "nested_extraction_failed",
    "actorops_discovery_ai_mixed_rows_unclassified": "mixed_rows_unclassified",
    "actorops_discovery_ai_dataset_run_unbound": "dataset_run_unbound",
    "actorops_discovery_ai_dataset_expansion_overflow": "dataset_expansion_overflow",
    "actorops_discovery_ai_observed_mapping_failed": "observed_mapping_failed",
    "actorops_discovery_output_sample_required": "output_sample_required",
    "actorops_discovery_input_plan_invalid": "input_plan_invalid",
    "actorops_discovery_route_type_uncertain": "route_type_uncertain",
    "actorops_replacement_sample_dataset_empty": "sample_dataset_empty",
    "actorops_replacement_observed_mapping_failed": "observed_mapping_failed",
}


def candidate_mapping_issue(candidate: CandidateRecord) -> str | None:
    return _PUBLIC_CODES.get(str(candidate.last_error_code or ""))


__all__ = ["candidate_mapping_issue"]
