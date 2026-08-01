"""Resolve the workspace-global AI selection for Actor discovery.

Actor discovery deliberately has no independent provider, model, or key pool.
Each job freezes the global AI configuration and the single SecretStore key
selected by ``config.ai.api_key_env`` when that job begins.
"""

from __future__ import annotations

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

    ready: bool
    unavailable_reason: str | None
    provider: str
    model: str
    key_name: str | None
    config: AIConfig | None

    def public_dict(self) -> dict[str, object]:
        return {
            "id": "global",
            "label": "当前全局 AI",
            "provider": self.provider,
            "model": self.model,
            "key_name": self.key_name,
            "ready": self.ready,
            "unavailable_reason": self.unavailable_reason,
        }


def resolve_global_discovery_ai(
    store: ServiceStore,
    *,
    data_dir: Path | str,
    workspace_id: str,
) -> GlobalDiscoveryAISelection:
    """Resolve exactly one configured global AI key without fallback."""

    try:
        global_config = StorageManager(str(data_dir)).load_config().ai
    except Exception:
        return GlobalDiscoveryAISelection(
            ready=False,
            unavailable_reason="global_ai_config_invalid",
            provider="",
            model="",
            key_name=None,
            config=None,
        )

    provider = str(global_config.provider.value).casefold()
    model = str(global_config.model or "").strip()
    env_name = str(global_config.api_key_env or "").strip()
    secret = (
        store.get_secret_ref_by_env(
            workspace_id=str(workspace_id),
            env_name=env_name,
        )
        if env_name
        else None
    )
    key_name = str(secret["name"]) if secret is not None else None

    reason: str | None = None
    if not bool(global_config.enabled):
        reason = "global_ai_disabled"
    elif provider not in SUPPORTED_DISCOVERY_AI_PROVIDERS:
        reason = "global_ai_provider_unsupported"
    elif not model:
        reason = "global_ai_model_missing"
    elif not env_name:
        reason = "global_ai_key_missing"
    elif secret is None:
        reason = "global_ai_key_not_registered"
    elif str(secret.get("kind") or "").casefold() != "ai":
        reason = "global_ai_key_kind_mismatch"
    elif str(secret.get("provider") or "").casefold() != provider:
        reason = "global_ai_key_provider_mismatch"
    else:
        try:
            is_set = bool(SecretStore(data_dir).status(env_name)["is_set"])
        except Exception:
            is_set = False
        if not is_set:
            reason = "global_ai_key_unavailable"

    return GlobalDiscoveryAISelection(
        ready=reason is None,
        unavailable_reason=reason,
        provider=provider,
        model=model,
        key_name=key_name,
        config=global_config if reason is None else None,
    )
