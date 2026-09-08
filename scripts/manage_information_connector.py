#!/usr/bin/env python3
"""Explicit per-user connector export and Gateway configuration, without model calls."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.agent_connections.service import AgentConnections
from src.services.agent_connections.connector_config import configure
from src.services.information_automations.connector_auth import provision, revoke
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore
from provision_openclaw_agent import private_write, validate_openclaw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'install', 'revoke'])
    parser.add_argument('--bundle-dir', type=Path)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--user-id')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--openclaw', default='openclaw')
    args = parser.parse_args()
    try:
        if args.action != 'revoke' and not args.bundle_dir:
            raise ValueError('Bundle directory required')
        if args.action in {'export', 'revoke'}:
            if not args.data_dir or not args.user_id or not (args.data_dir / 'service.db').is_file():
                raise ValueError('Existing data directory and user required')
            if args.action == 'export':
                args.bundle_dir.mkdir(mode=0o700)
            store = ServiceStore(args.data_dir)
            try:
                if args.action == 'revoke':
                    revoke(store, args.user_id)
                    print(json.dumps({'status': 'revoked'}))
                    return 0
                manifest, token = provision(store, SecretStore(args.data_dir), args.user_id)
                base, _ = AgentConnections(store, SecretStore(args.data_dir)).export(args.user_id)
                private_write(args.bundle_dir / 'manifest.json', json.dumps({**manifest, 'base': base}))
                SecretStore(args.bundle_dir).set(manifest['secret_ref'], token)
            finally:
                store.close()
        else:
            if not args.root:
                raise ValueError('Gateway root required')
            root = args.root.resolve(); path = root / 'openclaw.json'
            if path.is_symlink():
                raise ValueError('Regular Gateway config required')
            manifest = json.loads((args.bundle_dir / 'manifest.json').read_text())
            target, agent_id = configure(json.loads(path.read_text()), manifest['base'], root)
            candidate = root / ('.connector-' + uuid.uuid4().hex + '.json')
            try:
                private_write(candidate, json.dumps(target, indent=2))
                validate_openclaw(candidate, SecretStore(root, filename='.env').read(), args.openclaw)
                for field in ('workspace', 'agentDir'):
                    directory = Path(target['agents']['entries'][agent_id][field])
                    if directory.resolve() != directory:
                        raise ValueError('Connector directory cannot use symlinks')
                    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                private_write(root / ('openclaw.pre-connector-' + uuid.uuid4().hex + '.json'), path.read_text())
                os.replace(candidate, path)
            finally:
                candidate.unlink(missing_ok=True)
        print(json.dumps({'status': args.action + '_complete', 'model_verified': False, 'notification_sent': False}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
