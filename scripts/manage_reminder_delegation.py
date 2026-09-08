#!/usr/bin/env python3
"""Export an explicit reminder grant or install it into an existing personal Gateway."""
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.agent_connections.reminder_delegation import prepare, configure
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore
from provision_openclaw_agent import private_write, validate_openclaw

SKILL = '''---
name: personal-information-reminders
description: Prepare personal subscription reminders for explicit user confirmation.
---
Use list_my_information_automations to inspect the authenticated user's rules.
Use prepare_information_automation to prepare a draft only. Source IDs must come
from the user's subscriptions; never invent a notification target. Missing fields
may remain empty for the user to complete in the confirmation card.
Show the returned confirmation_card marker verbatim in the assistant response.
The web UI fetches the trusted rule and lets the user edit, test and confirm.
Never claim a draft is enabled or a notification was sent. Never use Cron or any
other tool to bypass user confirmation. The Agent cannot activate or send.
'''


def export(args):
    if not (args.data_dir / 'service.db').is_file():
        raise ValueError('Existing Service database required')
    args.bundle_dir.mkdir(mode=0o700)
    store = ServiceStore(args.data_dir)
    try:
        manifest, token = prepare(store, SecretStore(args.data_dir), args.user_id)
        for name, value in [('manifest.json', json.dumps(manifest)), ('token', token)]:
            fd = os.open(args.bundle_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(value + '\n')
    finally:
        store.close()


def install(args):
    token_path = args.bundle_dir / 'token'
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
        raise ValueError('Private credential file required')
    token = token_path.read_text().strip()
    manifest = json.loads((args.bundle_dir / 'manifest.json').read_text())
    if hashlib.sha256(token.encode()).hexdigest() != manifest['token_sha256']:
        raise ValueError('Credential mismatch')
    root = args.root.resolve()
    path = root / 'openclaw.json'
    if path.is_symlink():
        raise ValueError('Regular Gateway config required')
    target = configure(json.loads(path.read_text()), manifest, root)
    candidate = root / ('.reminder-' + uuid.uuid4().hex + '.json')
    secrets = SecretStore(root, filename='.env')
    try:
        private_write(candidate, json.dumps(target, indent=2) + '\n')
        validate_openclaw(candidate, {**secrets.read(), manifest['secret_ref']: token}, args.openclaw)
        skill = Path(target['agents']['entries'][manifest['base']['agent_id']]['workspace']) / 'skills' / 'personal-information-reminders'
        if skill.resolve() != skill:
            raise ValueError('Skill directory cannot use symlinks')
        skill.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_write(skill / 'SKILL.md', SKILL)
        private_write(root / ('openclaw.pre-reminders-' + uuid.uuid4().hex + '.json'), path.read_text())
        secrets.set(manifest['secret_ref'], token)
        os.replace(candidate, path)
    finally:
        candidate.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'install'])
    parser.add_argument('--bundle-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--user-id')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--openclaw', default='openclaw')
    args = parser.parse_args()
    if args.action == 'export' and (not args.data_dir or not args.user_id):
        parser.error('export requires --data-dir and --user-id')
    if args.action == 'install' and not args.root:
        parser.error('install requires --root')
    try:
        (export if args.action == 'export' else install)(args)
        print(json.dumps({'status': args.action + '_complete', 'runtime_verified': False}))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
