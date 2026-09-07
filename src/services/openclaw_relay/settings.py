"""Private deployment configuration; no credentials in public API payloads."""
import os
from pathlib import Path
from urllib.parse import urlsplit

RELAY_PATH = '/api/me/openclaw/socket'
SCOPES = ['operator.read', 'operator.write']


def enabled() -> bool:
    return os.getenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'false') == 'true'


def settings() -> tuple[str, str, Path]:
    url = os.environ.get('HORIZON_OPENCLAW_SERVER_URL', '')
    token = os.environ.get('HORIZON_OPENCLAW_SERVER_TOKEN', '')
    parsed = urlsplit(url)
    if parsed.scheme != 'wss' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid server OpenClaw URL')
    if not token:
        raise ValueError('Server OpenClaw credential is missing')
    path = Path(os.environ.get('HORIZON_OPENCLAW_RELAY_STATE', 'data/openclaw-relay'))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return url, token, path
