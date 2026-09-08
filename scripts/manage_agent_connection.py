#!/usr/bin/env python3
"""Service-host operator CLI. Credentials are exported only to a new private directory."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.services.agent_connections.service import AgentConnections, BindingError
from src.services.agent_connections.manifest import canonical
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore


def export_bundle(connections, user_id, destination):
    destination.mkdir(mode=0o700)  # Never overwrite an earlier or shared export.
    manifest, token = connections.export(user_id)
    for name, value in [('manifest.json', canonical(manifest)), ('token', token)]:
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(value + '\n')
    return {'status': 'exported', 'binding_id': manifest['binding_id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'prepare', 'export', 'activate', 'revoke', 'retire'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--mcp-url')
    parser.add_argument('--bundle-dir', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if not (args.data_dir / 'service.db').is_file():
        parser.error('Existing Service database required')
    store = ServiceStore(args.data_dir)  # No initialize or implicit migration.
    connections = AgentConnections(store, SecretStore(args.data_dir))
    try:
        if args.action == 'prepare':
            if not args.mcp_url:
                parser.error('--mcp-url required')
            connections.prepare(args.user_id, args.mcp_url)
        elif args.action == 'export':
            if not args.bundle_dir:
                parser.error('--bundle-dir required')
            print(json.dumps(export_bundle(connections, args.user_id, args.bundle_dir)))
            return 0
        elif args.action == 'activate':
            if not args.receipt:
                parser.error('--receipt required')
            connections.activate(args.user_id, json.loads(args.receipt.read_text()))
        elif args.action in {'revoke', 'retire'}:
            getattr(connections, args.action)(args.user_id)
        user = store.get_user(args.user_id)
        if not user:
            raise ValueError('User not found')
        print(json.dumps(connections.status(user)))
        return 0
    except Exception as error:
        # Never print raw config, database values, tokens, or transport error bodies.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'reason': str(error) if isinstance(error, BindingError) else 'Check inputs and target environment'}))
        return 1
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
