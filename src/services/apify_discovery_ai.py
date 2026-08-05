"""Resolve an administrator-selected workspace AI key for Actor discovery.

Actor discovery shares the workspace provider and model, while every selectable
SecretStore Key retains its own connection URL. Each job freezes the chosen Key
and its connection together with the workspace configuration when it begins.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..models import AIConfig
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .secret_store import SecretStore


SUPPORTED_DISCOVERY_AI_PROVIDERS = frozenset(
    {"anthropic", "deepseek", "gemini", "openai"}
)


@dataclass(frozen=True, slots=True)
class GlobalDiscoveryAISelection:
    """Frozen global AI selection plus a safe public readiness projection."""

    config_id: str
    secret_ref_id: str | None
    preferred: bool
    ready: bool
    unavailable_reason: str | None
    provider: str
    model: str
    key_name: str | None
    config: AIConfig | None

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.config_id,
            "label": self.key_name or "当前全局 AI",
            "provider": self.provider,
            "model": self.model,
            "key_name": self.key_name,
            "preferred": self.preferred,
            "ready": self.ready,
            "unavailable_reason": self.unavailable_reason,
        }


def _public_config_id(secret_ref_id: str) -> str:
    """Return a stable opaque selector value without exposing Secret metadata."""

    digest = hashlib.sha256(
        f"actor-discovery-global-ai:{secret_ref_id}".encode("utf-8")
    ).hexdigest()
    return f"global-ai-{digest[:24]}"


def _load_global_ai_config(data_dir: Path | str) -> AIConfig | None:
    try:
        return StorageManager(str(data_dir)).load_config().ai
    except Exception:
        return None


def _selection_from_secret(
    secret: dict[str, object],
    *,
    global_config: AIConfig,
    secret_store: SecretStore,
) -> GlobalDiscoveryAISelection:
    provider = str(global_config.provider.value).casefold()
    model = str(global_config.model or "").strip()
    secret_ref_id = str(secret.get("id") or "")
    env_name = str(secret.get("env_name") or "").strip()
    secret_provider = str(secret.get("provider") or "").casefold()
    reason: str | None = None
    if not bool(global_config.enabled):
        reason = "global_ai_disabled"
    elif provider not in SUPPORTED_DISCOVERY_AI_PROVIDERS:
        reason = "global_ai_provider_unsupported"
    elif not model:
        reason = "global_ai_model_missing"
    elif secret_provider != provider:
        reason = "global_ai_key_provider_mismatch"
    elif str(secret.get("kind") or "").casefold() != "ai":
        reason = "global_ai_key_kind_mismatch"
    elif str(secret.get("provider") or "").casefold() != provider:
        reason = "global_ai_key_provider_mismatch"
    elif not env_name:
        reason = "global_ai_key_missing"
    else:
        try:
            is_set = bool(secret_store.status(env_name)["is_set"])
        except Exception:
            is_set = False
        if not is_set:
            reason = "global_ai_key_unavailable"
    preferred = env_name == str(global_config.api_key_env or "").strip()
    return GlobalDiscoveryAISelection(
        config_id=_public_config_id(secret_ref_id),
        secret_ref_id=secret_ref_id,
        preferred=preferred,
        ready=reason is None,
        unavailable_reason=reason,
        provider=provider,
        model=model,
        key_name=str(secret.get("name") or "").strip() or None,
        config=(
            global_config.model_copy(
                update={
                    "api_key_env": env_name,
                    "base_url": str(secret.get("base_url") or "").strip() or None,
                }
            )
            if reason is None
            else None
        ),
    )


def list_global_discovery_ai_options(
    store: ServiceStore,
    *,
    data_dir: Path | str,
    workspace_id: str,
) -> tuple[GlobalDiscoveryAISelection, ...]:
    """List safe key choices for the currently saved global AI provider."""

    global_config = _load_global_ai_config(data_dir)
    if global_config is None:
        return ()
    provider = str(global_config.provider.value).casefold()
    secret_store = SecretStore(data_dir)
    selections = [
        _selection_from_secret(
            secret,
            global_config=global_config,
            secret_store=secret_store,
        )
        for secret in store.list_secret_refs(workspace_id=str(workspace_id))
        if str(secret.get("kind") or "").casefold() == "ai"
        and str(secret.get("provider") or "").casefold() == provider
    ]
    selections.sort(
        key=lambda item: (
            not item.preferred,
            (item.key_name or "").casefold(),
            item.config_id,
        )
    )
    return tuple(selections)


def resolve_global_discovery_ai_config_id(
    store: ServiceStore,
    *,
    data_dir: Path | str,
    workspace_id: str,
    ai_config_id: str,
) -> GlobalDiscoveryAISelection | None:
    """Resolve one opaque public choice from the current global catalog."""

    return next(
        (
            option
            for option in list_global_discovery_ai_options(
                store,
                data_dir=data_dir,
                workspace_id=workspace_id,
            )
            if option.config_id == ai_config_id
        ),
        None,
    )


def resolve_global_discovery_ai(
    store: ServiceStore,
    *,
    data_dir: Path | str,
    workspace_id: str,
    secret_ref_id: str | None = None,
) -> GlobalDiscoveryAISelection:
    """Resolve exactly one selected global AI key without fallback.

    ``secret_ref_id=None`` preserves upgraded databases by selecting the
    preferred key from ``config.ai.api_key_env`` until an administrator saves
    an explicit Discovery choice.
    """

    global_config = _load_global_ai_config(data_dir)
    if global_config is None:
        return GlobalDiscoveryAISelection(
            config_id="global-ai-unavailable",
            secret_ref_id=None,
            preferred=False,
            ready=False,
            unavailable_reason="global_ai_config_invalid",
            provider="",
            model="",
            key_name=None,
            config=None,
        )

    provider = str(global_config.provider.value).casefold()
    model = str(global_config.model or "").strip()
    preferred_env = str(global_config.api_key_env or "").strip()
    secret = store.get_secret_ref(str(secret_ref_id)) if secret_ref_id else None
    if secret is not None and str(secret.get("workspace_id")) != str(workspace_id):
        secret = None
    if secret_ref_id is None and preferred_env:
        secret = store.get_secret_ref_by_env(
            workspace_id=str(workspace_id),
            env_name=preferred_env,
        )

    if secret is not None:
        return _selection_from_secret(
            secret,
            global_config=global_config,
            secret_store=SecretStore(data_dir),
        )

    reason: str | None = None
    if not bool(global_config.enabled):
        reason = "global_ai_disabled"
    elif provider not in SUPPORTED_DISCOVERY_AI_PROVIDERS:
        reason = "global_ai_provider_unsupported"
    elif not model:
        reason = "global_ai_model_missing"
    elif secret_ref_id is not None:
        reason = "global_ai_selection_not_found"
    elif not preferred_env:
        reason = "global_ai_key_missing"
    else:
        reason = "global_ai_key_not_registered"

    return GlobalDiscoveryAISelection(
        config_id="global-ai-unavailable",
        secret_ref_id=None,
        preferred=False,
        ready=reason is None,
        unavailable_reason=reason,
        provider=provider,
        model=model,
        key_name=None,
        config=None,
    )
