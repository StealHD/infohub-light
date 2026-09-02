"""Resolve trusted subscription provenance for notification candidates."""

from __future__ import annotations

from typing import Any


def notification_candidate_subscription_ids(
    item: dict[str, Any],
    *,
    row_source_id: Any,
    row_subscription_id: Any,
    job: dict[str, Any],
) -> list[str]:
    """Combine item provenance with a matching source-fetch job boundary."""

    raw_subscription_ids = item.get("subscription_ids")
    subscription_ids = [
        str(value)
        for value in [
            *(
                raw_subscription_ids
                if isinstance(raw_subscription_ids, list)
                else []
            ),
            item.get("subscription_id"),
            row_subscription_id,
        ]
        if value
    ]
    raw_source_ids = item.get("source_ids")
    source_ids = {
        str(value)
        for value in [
            *(raw_source_ids if isinstance(raw_source_ids, list) else []),
            item.get("source_id"),
            row_source_id,
        ]
        if value
    }
    job_source_id = str(job.get("source_id") or "")
    if (
        job.get("job_type") == "source_fetch"
        and job_source_id in source_ids
        and job.get("subscription_id")
    ):
        subscription_ids.append(str(job["subscription_id"]))
    return list(dict.fromkeys(subscription_ids))
