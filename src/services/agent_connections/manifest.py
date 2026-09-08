"""Versioned, secret-free deployment manifest and authenticated operator receipt."""
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

READ_TOOLS = (
    'get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job',
    'get_source_setup_guide', 'search_bilibili_users', 'resolve_source', 'list_available_sources',
    'diagnose_source', 'diagnose_job', 'query_operation_logs',
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {
        'version', 'binding_id', 'user_id', 'workspace_id', 'agent_id', 'mcp_server',
        'secret_ref', 'mcp_url', 'delegation_id', 'token_sha256', 'tools',
    }:
        raise ValueError('Invalid binding manifest')
    identifier = manifest['binding_id']
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid binding identity')
    if (manifest['version'] != 1 or manifest['agent_id'] != 'ih-' + identifier
            or manifest['mcp_server'] != 'ih_' + identifier[:24]
            or manifest['secret_ref'] != 'INTELISCOPE_MCP_' + identifier.upper()
            or manifest['tools'] != list(READ_TOOLS)
            or not re.fullmatch(r'[a-f0-9]{64}', str(manifest['token_sha256']))):
        raise ValueError('Invalid binding policy')
    url = urlsplit(manifest['mcp_url'])
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or not (url.scheme == 'https' or url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost', '::1'})
            or url.path != '/mcp'):
        raise ValueError('MCP URL must be HTTPS /mcp (HTTP loopback allowed for tests)')
    return manifest


def receipt(manifest, token, config_digest):
    validate_manifest(manifest)
    body = {'binding_id': manifest['binding_id'], 'manifest_sha256': digest(manifest),
            'config_sha256': config_digest, 'verified_at': datetime.now(timezone.utc).isoformat(),
            'checks': ['config_valid', 'agent_policy', 'mcp_read_tools']}
    return {**body, 'signature': hmac.new(token.encode(), canonical(body).encode(), 'sha256').hexdigest()}


def validate_receipt(manifest, token, proof):
    body = {key: value for key, value in proof.items() if key != 'signature'}
    expected = hmac.new(token.encode(), canonical(body).encode(), 'sha256').hexdigest()
    if (set(proof) != {'binding_id', 'manifest_sha256', 'config_sha256', 'verified_at', 'checks', 'signature'}
            or not hmac.compare_digest(expected, str(proof.get('signature', '')))
            or body['binding_id'] != manifest['binding_id'] or body['manifest_sha256'] != digest(manifest)
            or not re.fullmatch(r'[a-f0-9]{64}', str(body['config_sha256']))
            or body['checks'] != ['config_valid', 'agent_policy', 'mcp_read_tools']):
        raise ValueError('Deployment receipt does not match this binding')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(body['verified_at'])).total_seconds()
    if not 0 <= age <= 3600:
        raise ValueError('Deployment receipt must be less than one hour old')
