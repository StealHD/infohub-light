"""Host-only supervised runtime; no web-controlled settings or commands."""
import os
import signal
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.agent_connections.analysis_supervisor import serve
from src.services.agent_connections.host_command import Host
from src.services.agent_connections.ssh_host import protected_file
from src.services.secret_store import SecretStore


def main():
    if len(sys.argv) != 2:
        raise ValueError('Host settings required')
    settings = Path(protected_file(sys.argv[1]))
    values = dotenv_values(settings)
    allowed = {'HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED', 'HORIZON_OPENCLAW_MANAGED_ROOT',
               'HORIZON_OPENCLAW_SERVER_URL', 'HORIZON_OPENCLAW_SERVER_TOKEN',
               'HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', 'INTELISCOPE_MANAGED_MCP_URL', 'INTELISCOPE_ANALYSIS_CATALOG_ONLY',
               'INTELISCOPE_OPENCLAW_PACKAGE'}
    if set(values) - allowed:
        raise ValueError('Unexpected settings')
    for name in allowed:
        os.environ.pop(name, None)
    os.environ.update({key: value for key, value in values.items() if value is not None})
    state = settings.parent / 'state'
    if state.is_symlink():
        raise ValueError('Unsafe device state')
    state.mkdir(mode=0o700, exist_ok=True)
    from src.logging_utils import configure_logging
    configure_logging(settings.parent / 'logs', service='cli')
    host = Host(SimpleNamespace(store=SimpleNamespace(data_dir=state), secret_values=SecretStore(state)))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    serve(host, stop)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Managed analysis supervisor unavailable', file=sys.stderr)
        raise SystemExit(1) from None
