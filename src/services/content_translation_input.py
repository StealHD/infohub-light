"""Authoritative translation input and model identity; no network calls."""

import hashlib
import json
import os
from dataclasses import dataclass

from ..models import AIConfig, AIProvider
from ..translation_errors import TranslationError
from ..storage.manager import StorageManager
from .secret_store import SecretStore
from .user_content_store import UserContentStore

PROMPT_VERSION = "body-zh-v1"


@dataclass(frozen=True)
class TranslationInput:
    text: str
    scope: str
    truncated: bool
    config: AIConfig
    cache_key: str


def read_source(store, user, article_id):
    stored = UserContentStore(store).get_item(
        workspace_id=user["workspace_id"], user_id=user["id"], article_id=article_id
    )
    if stored is None:
        raise TranslationError("not_found", "内容不存在或无法访问。", 404)
    item = stored["item"]
    content = (item.get("presentation") or {}).get("content") or {}
    body = str(stored.get("body_text") or "").strip()
    if stored.get("body_completeness") == "captured" and body:
        return body[:20_000], "body", bool(stored.get("body_truncated")) or len(body) > 20_000
    # Legacy stored bodies may be AI summaries. Only an explicit source excerpt
    # is eligible; never use complete_content_presentation's synthetic fallback.
    excerpt = str(content.get("excerpt") or item.get("excerpt") or "").strip()
    if not excerpt:
        raise TranslationError("translation_no_text", "暂无可翻译正文。")
    return excerpt[:20_000], "excerpt", bool(content.get("excerpt_truncated")) or len(excerpt) > 20_000


def model_config(store, user):
    try:
        config = StorageManager(str(store.data_dir)).load_config().ai
    except (OSError, ValueError):
        raise TranslationError("translation_model_unavailable", "请在 AI 设置中配置模型。") from None
    secrets = SecretStore(store.data_dir)
    secrets.load_into_environ()
    ref = store.get_secret_ref_by_env(workspace_id=user["workspace_id"], env_name=config.api_key_env)
    if ref is not None:
        if ref["kind"] != "ai":
            raise TranslationError("translation_model_unavailable", "请在 AI 设置中选择有效的 AI 密钥。")
        config = config.model_copy(update={
            "provider": AIProvider(ref["provider"]), "base_url": ref.get("base_url") or None,
        })
    if not config.model.strip() or (
        config.provider != AIProvider.OLLAMA and not secrets.status(config.api_key_env)["is_set"]
    ):
        raise TranslationError("translation_model_unavailable", "请在 AI 设置中配置可用的模型和密钥。")
    identity = {
        "provider": config.provider.value, "model": config.model,
        "base_url": config.base_url, "api_key_env": config.api_key_env,
        "secret_version": ref.get("version", 0) if ref else 0,
        "credential_fingerprint": hashlib.sha256(os.getenv(config.api_key_env, "").encode()).hexdigest(),
        "azure_endpoint": os.getenv(config.azure_endpoint_env or "", ""),
        "azure_endpoint_env": config.azure_endpoint_env, "api_version": config.api_version,
    }
    return config, identity


def prepare_input(store, user, article_id):
    text, scope, truncated = read_source(store, user, article_id)
    config, identity = model_config(store, user)
    raw = json.dumps([user["workspace_id"], user["id"], article_id, text, scope, truncated,
                      "zh-CN", PROMPT_VERSION, identity], ensure_ascii=False, sort_keys=True)
    return TranslationInput(text, scope, truncated, config, hashlib.sha256(raw.encode()).hexdigest())
