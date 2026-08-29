"""Bounded AI assistance for exact ActorOps v2 discovery manifests."""

from __future__ import annotations

import inspect
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .discovery_ai_prompt import mapping_prompt, mapping_system_prompt
from .ports import DiscoveryAiResult, DiscoveryMapping, DiscoveryRevision


_MAX_MAPPINGS = 1
_MAX_MANIFEST_BYTES = 16 * 1024
_SAFE_AI_ERRORS = frozenset({
    "missing_target_input", "missing_required_input_value", "missing_native_id",
    "missing_url", "missing_published_at", "missing_text", "missing_identity",
    "missing_post_author_handle", "output_not_content_items", "ambiguous_output",
    "wrong_actor_type", "nested_content_items", "named_dataset_required",
    "output_schema_incomplete", "target_identity_derivable",
    "relative_published_at", "nested_extraction_failed",
    "mixed_rows_unclassified", "dataset_run_unbound",
    "dataset_expansion_overflow", "observed_mapping_failed",
})


@dataclass(slots=True)
class ActorOpsDiscoveryAiMapper:
    """One bounded batch of public-schema mapping proposals.

    The model sees only an opaque route key and public input/output field names.
    It never receives a source target, a credential, or returned content.  Its
    raw response is discarded after strict JSON extraction; the generic
    Discovery layer independently proves every retained pointer against the
    exact Build schema.
    """

    client: Any
    config_id: str
    store: Any
    workspace_id: str
    user_id: str
    provider: str

    async def map(self, route_key: object, revisions: Sequence[DiscoveryRevision]) -> DiscoveryAiResult:
        selected = tuple(revisions[:_MAX_MAPPINGS])
        if not selected:
            return DiscoveryAiResult(mappings={}, config_id=self.config_id)
        from ..quota import QuotaService

        QuotaService(self.store).admit_ai_attempt(
            workspace_id=self.workspace_id, user_id=self.user_id, provider=self.provider,
        )
        started = time.monotonic()
        raw = ""
        try:
            raw = await self.client.complete(
                mapping_system_prompt(),
                json.dumps(_prompt(route_key, selected), ensure_ascii=False, separators=(",", ":")),
                temperature=0.0,
                max_tokens=12_288,
            )
            parsed = _object(raw)
        except Exception:
            parsed = {}
        metrics = getattr(self.client, "last_completion_metrics", None)
        mappings: dict[str, DiscoveryMapping] = {}
        for revision in selected:
            mapping = _mapping(parsed.get(revision.actor_id))
            if mapping is not None:
                mappings[revision.actor_id] = mapping
        return DiscoveryAiResult(
            mappings=mappings, config_id=self.config_id,
            input_tokens=getattr(metrics, "input_tokens", None),
            completion_tokens=getattr(metrics, "completion_tokens", None),
            reasoning_tokens=getattr(metrics, "reasoning_tokens", None),
            finish_reason=getattr(metrics, "finish_reason", None),
            latency_ms=int((time.monotonic() - started) * 1000),
            response_bytes=getattr(metrics, "response_bytes", len(raw.encode("utf-8"))),
        )

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result


def open_actorops_discovery_ai_mapper(
    *, store: Any, data_dir: str, workspace_id: str, user_id: str
) -> ActorOpsDiscoveryAiMapper | None:
    """Resolve the approved global AI configuration without storing a secret."""

    from ..apify_discovery_ai import resolve_global_discovery_ai
    from ..secret_store import SecretStore
    from .mapping_ai_client import create_actor_mapping_ai_client

    selection = resolve_global_discovery_ai(
        store, data_dir=data_dir, workspace_id=workspace_id,
    )
    if not selection.ready or selection.config is None:
        return None
    config = selection.config.model_copy(
        update={"enabled": True, "temperature": 0.0, "max_tokens": 12_288}
    )
    api_key = (
        SecretStore(data_dir).read().get(config.api_key_env)
        or os.getenv(config.api_key_env)
    )
    if not str(api_key or "").strip():
        return None
    try:
        client = create_actor_mapping_ai_client(
            config,
            api_key=str(api_key),
            timeout_seconds=90,
        )
    except Exception:
        return None
    return ActorOpsDiscoveryAiMapper(
        client=client, config_id=selection.config_id, store=store,
        workspace_id=workspace_id, user_id=user_id, provider=selection.provider,
    )


def _prompt(route_key: object, revisions: Sequence[DiscoveryRevision]) -> dict[str, object]:
    return mapping_prompt(route_key, revisions)


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > _MAX_MANIFEST_BYTES * _MAX_MAPPINGS:
        return {}
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    mappings = parsed.get("mappings") or parsed.get("candidates")
    if isinstance(mappings, Mapping):
        return mappings
    if isinstance(mappings, Sequence) and not isinstance(mappings, (str, bytes)):
        return {
            str(item.get("actor_id") or item.get("actorId")): item.get("manifest", item)
            for item in mappings
            if isinstance(item, Mapping) and str(item.get("actor_id") or item.get("actorId") or "").strip()
        }
    results = parsed.get("results")
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes)):
        return {
            str(item.get("actor_id") or item.get("actorId")): item
            for item in results
            if isinstance(item, Mapping)
            and str(item.get("actor_id") or item.get("actorId") or "").strip()
        }
    # Some compliant models omit the optional outer wrapper and return the
    # Actor-ID map directly.  Retain it only when every key resembles a public
    # Actor slug and every value is a prospective manifest object/string.
    if parsed and all(
        isinstance(key, str) and "/" in key and isinstance(item, (Mapping, str))
        for key, item in parsed.items()
    ):
        return parsed
    return {}


def _manifest_json(value: object) -> str | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, Mapping):
        return None
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded if len(encoded.encode("utf-8")) <= _MAX_MANIFEST_BYTES else None


def _mapping(value: object) -> DiscoveryMapping | None:
    if not isinstance(value, Mapping):
        return None
    status = str(value.get("status") or "").strip().casefold()
    if status == "unmappable":
        code = str(value.get("error_code") or "").strip().casefold()
        return (
            DiscoveryMapping(None, f"actorops_discovery_ai_{code}")
            if code in _SAFE_AI_ERRORS
            else None
        )
    manifest = value.get("manifest") if status == "mapped" else value
    manifest_json = _manifest_json(manifest)
    return DiscoveryMapping(manifest_json) if manifest_json is not None else None


__all__ = ["ActorOpsDiscoveryAiMapper", "open_actorops_discovery_ai_mapper"]
