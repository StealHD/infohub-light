"""Private deployment configuration; no credentials in public API payloads."""
import os
from pathlib import Path
from urllib.parse import urlsplit

RELAY_PATH = '/api/me/openclaw/socket'
SCOPES = ['operator.read', 'operator.write']


def enabled() -> bool:
    return os.getenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'false') == 'true'


def configuration() -> tuple[str, str]:
    url = os.environ.get('HORIZON_OPENCLAW_SERVER_URL', '')
    token = os.environ.get('HORIZON_OPENCLAW_SERVER_TOKEN', '')
    parsed = urlsplit(url)
    local_ws = (parsed.scheme == 'ws' and parsed.hostname in {'127.0.0.1', '::1', 'localhost'}
                and os.getenv('HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED') == 'true')
    if (parsed.scheme != 'wss' and not local_ws) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid server OpenClaw URL')
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid server OpenClaw port')
    if not token.strip():
        raise ValueError('Server OpenClaw credential is missing')
    return url, token


def settings() -> tuple[str, str, Path]:
    url, token = configuration()
    path = Path(os.environ.get('HORIZON_OPENCLAW_RELAY_STATE', 'data/openclaw-relay'))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return url, token, path
