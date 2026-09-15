"""Bounded GET of an existing settled acquisition Dataset, without reservations."""

from __future__ import annotations

import json
import os
from urllib.parse import quote

import httpx

from ..secret_store import SecretStore


class KnownDatasetError(ValueError):
    pass


def read_known_dataset(store, attempt, *, transport=None):
    """Use only the credential associated with the exact original Run."""
    if (attempt["kind"] != "fetch" or attempt["status"] != "succeeded"
            or attempt["result_state"] != "validated" or not attempt["cost_final"]
            or not attempt["dataset_id"] or not attempt["remote_run_id"]):
        raise KnownDatasetError("instagram_dataset_ineligible")
    rows = store.connect().execute(
        """SELECT s.env_name FROM apify_actor_runs r
           JOIN secret_refs s ON s.id=r.secret_id AND s.workspace_id=r.workspace_id
             AND s.version=r.secret_version
           WHERE r.workspace_id=? AND r.logical_run_id=? AND r.purpose='acquisition'
             AND r.remote_run_id=? AND r.dataset_id=? AND r.charge_final=1
           LIMIT 2""",
        (attempt["workspace_id"], attempt["attempt_id"], attempt["remote_run_id"],
         attempt["dataset_id"]),
    ).fetchall()
    if len(rows) != 1:
        raise KnownDatasetError("instagram_dataset_identity_unproven")
    name = rows[0]["env_name"]
    token = SecretStore(store.data_dir).read().get(name) or os.getenv(name)
    if not token:
        raise KnownDatasetError("instagram_dataset_credential_missing")
    limit = min(max(int(attempt["max_items"]), 1), 100)
    url = "https://api.apify.com/v2/datasets/" + quote(attempt["dataset_id"], safe="") + "/items"
    try:
        with httpx.Client(transport=transport, timeout=30, follow_redirects=False) as client:
            with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"},
                               params={"clean": "true", "limit": str(limit)}) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 8 * 1024 * 1024:
                        raise KnownDatasetError("instagram_dataset_too_large")
        value = json.loads(body)
        if not isinstance(value, list) or len(value) > limit or any(
            not isinstance(row, dict) for row in value
        ):
            raise KnownDatasetError("instagram_dataset_shape_invalid")
        return tuple(value)
    except KnownDatasetError:
        raise
    except Exception:
        raise KnownDatasetError("instagram_dataset_unavailable") from None
