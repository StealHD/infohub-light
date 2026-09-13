"""Read the signed-in user's configured OpenClaw models without starting analysis."""
import asyncio
from pathlib import Path

from .connector_auth import authenticate, provision
from .model_catalog import Capabilities, catalog, sync_catalog
from .model_discovery import rpc_models
from .rules import RuleError


def configured_models(payload):
    """Project only currently available Gateway models; never apply a local allowlist."""
    models, seen = [], set()
    for row in payload.get('models', []):
        if not isinstance(row, dict) or row.get('available') is False:
            continue
        raw_id, provider = row.get('id'), row.get('provider')
        if not isinstance(raw_id, str) or not isinstance(provider, str) or not raw_id or not provider:
            continue
        model_id = raw_id if raw_id.startswith(provider + '/') else provider + '/' + raw_id
        if model_id in seen:
            continue
        seen.add(model_id)
        thinking = [level['id'] for level in row.get('thinkingLevels', [])
                    if isinstance(level, dict) and isinstance(level.get('id'), str)]
        models.append({'id': model_id, 'name': row.get('name') if isinstance(row.get('name'), str) else model_id,
                       'thinking_levels': thinking})
    return sorted(models, key=lambda model: model['id'])


def refresh(store, secret_store, settings, data_path, user_id):
    """Synchronously refresh catalog metadata through the configured personal Agent."""
    if not settings.enabled:
        raise RuleError('openclaw_gateway_unavailable', 'OpenClaw 聊天 Gateway 未启用，无法读取模型目录。', 503)
    base, connector_token = provision(store, secret_store, user_id)
    gateway_token = secret_store.read().get('HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', '').strip()
    if not gateway_token:
        raise RuleError('openclaw_gateway_credential_missing', 'OpenClaw 管理授权未配置，无法读取模型目录。', 503)
    try:
        payload = asyncio.run(asyncio.wait_for(
            rpc_models(settings.default_gateway_url, gateway_token, base['agent_id'],
                       Path(data_path) / 'openclaw-relay' / 'model-catalog'),
            timeout=30,
        ))
    except (OSError, TimeoutError, ValueError, asyncio.TimeoutError):
        raise RuleError('openclaw_model_catalog_unavailable', '无法读取本机 OpenClaw 模型目录，请检查 Gateway 连接后刷新。', 503) from None
    machine = authenticate(store, connector_token)
    # A successful `models.list` proves only that the user's configured model
    # directory is readable.  It must never attest to, enable, or downgrade the
    # independent analysis runner.
    sync_catalog(store, machine, Capabilities(protocol_version=2,
                                               models=configured_models(payload)),
                 runtime_verified=False)
    from .rules import transaction
    with transaction(store) as conn:
        conn.execute("UPDATE information_model_catalog SET blocked_models_json='[]' WHERE binding_id=?",
                     (base['binding_id'],))
    return catalog(store, base['binding_id'])
