"""Preview or apply media-only repair for one explicitly selected Instagram post."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.instagram_media_repair import (
    MediaRepairError, apply_media_repair, preview_media_repair,
)
from src.storage.service_store import ServiceStore
from src.logging_utils import configure_logging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-preview")
    args = parser.parse_args()
    if args.apply and not args.expected_preview:
        parser.error("--apply requires --expected-preview from a preview")
    if not (Path(args.data_dir) / "service.db").is_file():
        parser.error("existing service.db is required")
    store = ServiceStore(args.data_dir)
    try:
        plan = preview_media_repair(store, workspace_id=args.workspace_id,
                                    user_id=args.user_id, source_id=args.source_id,
                                    article_id=args.article_id)
        if args.apply:
            configure_logging(Path(args.data_dir).resolve().parent / "logs", service="cli")
        result = apply_media_repair(store, plan, expected_preview=args.expected_preview) if args.apply else plan.public()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except MediaRepairError as error:
        print(json.dumps({"status": "blocked", "code": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "code": "instagram_media_repair_failed"}))
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
