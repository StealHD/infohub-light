#!/usr/bin/env python3
"""Pull semantic work with private machine credentials; never send notifications."""
import argparse
import json
import sys
import ssl
import httpx
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.secret_store import SecretStore
from src.services.information_automations.connector_runner import InformationConnector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-url', required=True)
    parser.add_argument('--gateway-url', required=True)
    parser.add_argument('--secret-dir', type=Path, required=True)
    parser.add_argument('--service-secret-ref', required=True)
    parser.add_argument('--gateway-secret-ref', required=True)
    parser.add_argument('--gateway-secret-dir', type=Path, required=True)
    parser.add_argument('--gateway-secret-file', default='.env')
    parser.add_argument('--agent-id', required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--gateway-ca', type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    values = SecretStore(args.secret_dir).read()
    gateway_values = SecretStore(args.gateway_secret_dir, filename=args.gateway_secret_file).read()
    tls = ssl.create_default_context()
    if args.gateway_ca:
        tls.load_verify_locations(cafile=str(args.gateway_ca))
    connector = InformationConnector(service_url=args.service_url, gateway_url=args.gateway_url,
        service_token=values[args.service_secret_ref], gateway_token=gateway_values[args.gateway_secret_ref],
        agent_id=args.agent_id, journal=args.journal.resolve(), client=httpx.Client(timeout=75, follow_redirects=False, verify=tls))
    try:
        while True:
            try:
                result = connector.run_once()
            except Exception as error:
                result = {'status': 'connector_unavailable', 'error_type': type(error).__name__, 'retry_after': 30}
            print(json.dumps(result), flush=True)
            if args.once:
                return 0 if result['status'] != 'connector_unavailable' else 1
            time.sleep(max(1, min(60, result.get('retry_after', 15))))
    finally:
        connector.close()


if __name__ == '__main__':
    raise SystemExit(main())
