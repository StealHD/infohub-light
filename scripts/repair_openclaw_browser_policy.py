#!/usr/bin/env python3
"""Preview a public-web browser policy repair; --apply requires the preview's config hash."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.services.agent_connections.browser_policy import repair_browser_policy
from src.services.agent_skill_gateway import AgentSkillGateway
from src.services.secret_store import SecretStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-hash')
    args = parser.parse_args(argv)
    if args.apply != bool(args.expected_hash):
        parser.error('--apply and --expected-hash must be supplied together')
    if not args.data_dir.is_dir():
        parser.error('Existing Service data directory required')
    try:
        secrets = SecretStore(args.data_dir)
        secrets.load_into_environ()
        gateway = AgentSkillGateway(secrets, args.data_dir)
        result = asyncio.run(repair_browser_policy(gateway, expected_hash=args.expected_hash))
        print(json.dumps(result))
        return 2 if result['status'] == 'saved_pending_reload' else 0
    except Exception as error:
        # No raw upstream errors, URLs, config or secrets in operator output.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'reason': 'Inspect browser policy and current configuration before retrying'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
