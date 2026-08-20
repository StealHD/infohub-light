#!/usr/bin/env python3
"""Raise YouTube and Instagram Actor Route per-run price caps to $0.10.

The paid-Canary charge ceiling and the Route per-run cap are two separate
bounds.  Before this change the per-candidate Canary charge was hard-limited
to $0.02 (see ``apify_actor_ops`` validation profile), so a Route cap above
$0.02 could never actually be exercised.  After that code change the Route
per-run cap must be raised to $0.10 for the YouTube and Instagram routes so
that more Store candidates (priced between $0.02 and $0.10) survive the
``actor_price_above_route_cap`` metadata filter and can be paid-validated.

This is a data-value migration, not a schema migration: it drives the same
atomic ``set_route_price_cap`` path as the admin ``price-cap`` endpoint, so it
bumps ``generation`` and keeps pool-stage/activation guards intact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import ServiceStore

TARGET_ROUTE_KEYS = frozenset({"youtube/channel/items", "instagram/profile/items"})
TARGET_CAP_USD = 0.10


def migrate(data_dir: Path, *, apply: bool) -> dict:
    store = ServiceStore(str(data_dir))
    store.initialize()
    ops = ApifyActorOpsService(store, workspace_id="default")

    changes = []
    for route in ops.list_routes():
        key = str(route.get("route_key") or "")
        if key not in TARGET_ROUTE_KEYS:
            continue
        current_cap = float(route.get("per_run_cap_usd") or 0.02)
        entry = {
            "route_key": key,
            "route_id": str(route["route_id"]),
            "generation": int(route["generation"]),
            "current_cap_usd": current_cap,
            "target_cap_usd": TARGET_CAP_USD,
        }
        if abs(current_cap - TARGET_CAP_USD) < 1e-9:
            entry["action"] = "unchanged"
            changes.append(entry)
            continue
        entry["action"] = "update" if apply else "would_update"
        if apply:
            updated = ops.set_route_price_cap(
                str(route["route_id"]),
                per_run_cap_usd=TARGET_CAP_USD,
                expected_generation=int(route["generation"]),
            )
            entry["new_cap_usd"] = float(updated["per_run_cap_usd"])
            entry["new_generation"] = int(updated["generation"])
        changes.append(entry)
    return {"apply": apply, "routes": changes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    import json

    print(json.dumps(migrate(args.data_dir, apply=args.apply), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
