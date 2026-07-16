#!/usr/bin/env python3
"""One-call DeepSeek smoke against one already captured article."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from src.ai.client import AIClient, create_ai_client
from src.ai.tokens import get_usage_snapshot, reset_usage
from src.models import AIConfig, AIProvider
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore


PROVIDER = "deepseek"
MODEL = "deepseek-v4-flash"
KEY_ENV = "DEEPSEEK_API_KEY"
BASE_URL = "https://api.deepseek.com"
REQUEST_TIMEOUT_SECONDS = 10.0

ModelPreflight = Callable[[AIClient, str], Awaitable[None]]


def _parse_json(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _preflight_model(client: AIClient, model: str) -> None:
    raw_client = getattr(client, "client", None)
    models = getattr(raw_client, "models", None)
    list_models = getattr(models, "list", None)
    if not callable(list_models):
        raise RuntimeError("DeepSeek client does not expose models.list")

    response = await list_models()
    available_models = getattr(response, "data", None)
    if available_models is None:
        raise RuntimeError("DeepSeek models.list response has no model data")
    if not any(getattr(candidate, "id", None) == model for candidate in available_models):
        raise LookupError(f"DeepSeek model is not available: {model}")


def _bound_production_client(client: AIClient) -> None:
    if not hasattr(client, "_supports_temperature"):
        raise RuntimeError(
            "DeepSeek client cannot guarantee temperature-free one-shot completion"
        )
    try:
        client._supports_temperature = False  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        raise RuntimeError(
            "DeepSeek client cannot guarantee temperature-free one-shot completion"
        ) from None
    if getattr(client, "_supports_temperature", None) is not False:
        raise RuntimeError(
            "DeepSeek client cannot guarantee temperature-free one-shot completion"
        )
    raw_client = getattr(client, "client", None)
    with_options = getattr(raw_client, "with_options", None)
    if not callable(with_options):
        raise RuntimeError("DeepSeek client does not expose with_options")
    client.client = with_options(  # type: ignore[attr-defined]
        max_retries=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


async def _preflight_and_complete(
    *,
    client: AIClient,
    model_preflight: ModelPreflight,
    title: str,
    body: str,
) -> str:
    await model_preflight(client, MODEL)
    return await client.complete(
        system="Return one compact JSON object that analyzes the supplied article. Do not use markdown.",
        user=(
            f"Title: {title}\nContent: {body}\n"
            "Required keys: score (0-10), summary_zh, channel, topics (array)."
        ),
        temperature=0.0,
        max_tokens=384,
    )


def run_smoke(
    *,
    data_dir: Path | str,
    article_id: str,
    client_factory: Callable[[AIConfig], AIClient] | None = None,
    model_preflight: ModelPreflight | None = None,
) -> dict[str, Any]:
    """Preflight the model, perform at most one completion, and return no content."""

    store = ServiceStore(data_dir)
    store.initialize()
    try:
        row = store.connect().execute(
            """
            SELECT item_json, body_text
            FROM user_content_items
            WHERE article_id = ? AND body_completeness = 'captured'
            ORDER BY last_seen_at DESC LIMIT 1
            """,
            (article_id,),
        ).fetchone()
    finally:
        store.close()
    if row is None:
        raise LookupError("captured smoke article not found")
    try:
        item = json.loads(str(row["item_json"] or "{}"))
    except json.JSONDecodeError:
        item = {}
    title = str(item.get("title") or article_id) if isinstance(item, dict) else article_id
    body = str(row["body_text"] or "")[:4000]

    config = AIConfig(
        enabled=True,
        provider=AIProvider.DEEPSEEK,
        model=MODEL,
        base_url=BASE_URL,
        api_key_env=KEY_ENV,
        max_tokens=384,
        analysis_max_output_tokens=384,
        languages=["zh"],
    )
    if client_factory is None:
        SecretStore(data_dir).load_into_environ()
        client = create_ai_client(config)
        _bound_production_client(client)
    else:
        client = client_factory(config)

    reset_usage()
    response = asyncio.run(
        _preflight_and_complete(
            client=client,
            model_preflight=model_preflight or _preflight_model,
            title=title,
            body=body,
        )
    )
    parsed = _parse_json(response)
    if parsed is None or parsed.get("score") is None or not parsed.get("summary_zh"):
        raise ValueError("provider response did not satisfy the smoke JSON contract")
    usage = get_usage_snapshot().per_provider.get(PROVIDER)
    return {
        "provider": PROVIDER,
        "model": MODEL,
        "input_tokens": int(usage.input_tokens if usage else 0),
        "output_tokens": int(usage.output_tokens if usage else 0),
        "status": "succeeded",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded DeepSeek analysis request")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--article-id", required=True)
    args = parser.parse_args()
    try:
        report = run_smoke(data_dir=args.data_dir, article_id=args.article_id)
    except Exception:
        report = {
            "provider": PROVIDER,
            "model": MODEL,
            "input_tokens": 0,
            "output_tokens": 0,
            "status": "failed",
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
