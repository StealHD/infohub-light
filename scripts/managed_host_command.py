"""Forced-command stdio entrypoint; never prints secrets or upstream errors."""
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
from src.services.agent_connections.host_command import execute
from src.services.agent_connections.managed_host import ManagedReloadPending
from src.services.agent_connections.ssh_host import protected_file
from src.services.secret_store import SecretStore


def main():
    try:
        signal.alarm(180)
        if os.environ.get('SSH_ORIGINAL_COMMAND') != 'inteliscope-managed-v1' or len(sys.argv) != 2:
            raise ValueError('Forced command required')
        settings = Path(protected_file(sys.argv[1]))
        values = dotenv_values(settings)
        names = {'HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED', 'HORIZON_OPENCLAW_MANAGED_ROOT',
                 'HORIZON_OPENCLAW_SERVER_URL', 'HORIZON_OPENCLAW_SERVER_TOKEN',
                 'HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', 'INTELISCOPE_MANAGED_MCP_URL'}
        if set(values) - names:
            raise ValueError('Unexpected host settings')
        for name in names:
            os.environ.pop(name, None)
        os.environ.update({key: value for key, value in values.items() if value is not None})
        raw = sys.stdin.buffer.readline(32769)
        if len(raw) > 32768:
            raise ValueError('Oversized request')
        state = settings.parent / 'state'
        if state.is_symlink():
            raise ValueError('Unsafe device state')
        state.mkdir(mode=0o700, exist_ok=True)
        context = SimpleNamespace(store=SimpleNamespace(data_dir=state), secret_values=SecretStore(state))
        def emit(value):
            print(json.dumps(value), flush=True)
            if 'phase' in value:
                acknowledgement = sys.stdin.buffer.readline(1025)
                if json.loads(acknowledgement) != {'phase_ack': value['phase']}:
                    raise ValueError('Service authorization acknowledgement required')
        result = asyncio.run(execute(json.loads(raw), context, emit))
        emit({'result': result})
        return 0
    except ManagedReloadPending:
        print(json.dumps({'error': 'reload_pending'}), flush=True)
        return 1
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
