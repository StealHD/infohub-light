"""Exact owned-entry removal without agents.delete's session-index purge."""
import json
import os
import uuid
from .managed_host import ManagedSetupError


def remove_config(root, before, manifest):
    path = root / 'openclaw.json'
    config = json.loads(before)
    config.get('agents', {}).get('entries', {}).pop(manifest['agent_id'], None)
    config.get('mcp', {}).get('servers', {}).pop(manifest['mcp_server'], None)
    temporary = root / ('.inteliscope-remove-' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink() or path.read_bytes() != before:
            raise ManagedSetupError('配置同时被修改，未覆盖。')
        os.replace(temporary, path)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
