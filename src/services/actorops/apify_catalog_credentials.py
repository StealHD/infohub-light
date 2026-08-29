"""Purpose-aware credential resolution for read-only Apify Catalog calls."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from typing import Literal, cast

from ...storage.service_store import ServiceStore
from ..secret_store import SecretStore, SecretValueError


CatalogPurpose = Literal["acquisition", "validation"]


@dataclass(frozen=True, slots=True)
class ApifyCatalogCredential:
    """Private Catalog credential material; the token is excluded from repr."""

    env_name: str
    role: CatalogPurpose
    token: str = field(repr=False)


def resolve_apify_catalog_credential(
    store: ServiceStore,
    *,
    workspace_id: str,
    data_dir: str,
    purpose: str = "acquisition",
) -> ApifyCatalogCredential | None:
    """Resolve the credential domain used by one public Catalog read.

    Validation prefers its dedicated member.  Only an absent dedicated member
    falls back to the active acquisition credential, matching paid-run lease
    selection.  A configured but unusable validation member fails closed.
    """

    normalized = str(purpose).strip().casefold()
    if normalized not in {"acquisition", "validation"}:
        raise ValueError("purpose must be acquisition or validation")
    connection = store.connect()
    if normalized == "validation":
        row = _validation_row(connection, workspace_id)
        if row is not None:
            if str(row["status"]) != "standby":
                return None
            return _materialize(row, data_dir=data_dir)
    row = _active_acquisition_row(connection, workspace_id)
    return _materialize(row, data_dir=data_dir) if row is not None else None


def _validation_row(
    connection: sqlite3.Connection, workspace_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT member.role, member.status, secret.env_name
             FROM apify_key_pool_members AS member
             JOIN secret_refs AS secret
               ON secret.workspace_id=member.workspace_id
              AND secret.id=member.secret_id
            WHERE member.workspace_id=? AND member.role='validation'
            LIMIT 1""",
        (workspace_id,),
    ).fetchone()


def _active_acquisition_row(
    connection: sqlite3.Connection, workspace_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT member.role, member.status, secret.env_name
             FROM apify_key_pool_state AS state
             JOIN apify_key_pool_members AS member
               ON member.workspace_id=state.workspace_id
              AND member.secret_id=state.active_secret_id
             JOIN secret_refs AS secret
               ON secret.workspace_id=member.workspace_id
              AND secret.id=member.secret_id
            WHERE state.workspace_id=?
              AND state.status='ready'
              AND member.role='acquisition'
              AND member.status='active'
            LIMIT 1""",
        (workspace_id,),
    ).fetchone()


def _materialize(
    row: sqlite3.Row, *, data_dir: str
) -> ApifyCatalogCredential | None:
    try:
        env_name = SecretStore.validate_env_name(str(row["env_name"]))
    except (IndexError, KeyError, TypeError, SecretValueError):
        return None
    value = SecretStore(data_dir).read().get(env_name) or os.getenv(env_name)
    token = str(value or "").strip()
    if not token:
        return None
    role = str(row["role"])
    if role not in {"acquisition", "validation"}:
        return None
    return ApifyCatalogCredential(env_name, cast(CatalogPurpose, role), token)


__all__ = ["ApifyCatalogCredential", "resolve_apify_catalog_credential"]
