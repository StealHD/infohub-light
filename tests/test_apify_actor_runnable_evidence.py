"""Lock the runnable-evidence admission rule for Actor discovery.

The Store search already excludes unrunnable Actors via
``includeUnrunnableActors=False``, and the Actor detail response no longer
reliably retains ``isRunnable``/``canRun``.  A search-discovered candidate must
therefore be admitted when the flag is absent, while a direct/preferred
candidate still requires positive runnable evidence.
"""

from __future__ import annotations

import pytest

from src.services.apify_actor_discovery import ActorDiscoveryError
from src.services.apify_actor_discovery_store_policy import require_runnable_evidence


def _reject(code: str) -> ActorDiscoveryError:
    return ActorDiscoveryError(code, "rejected", status_code=422)


def test_positive_flag_admits_without_store_omission() -> None:
    require_runnable_evidence(
        {"isRunnable": True},
        allow_store_runnable_omission=False,
        reject=_reject,
    )


def test_negative_flag_rejects_not_runnable() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        require_runnable_evidence(
            {"isRunnable": False},
            allow_store_runnable_omission=False,
            reject=_reject,
        )
    assert exc.value.code == "actor_not_runnable"


def test_missing_flag_with_store_omission_admits() -> None:
    require_runnable_evidence(
        {"isPublic": True},
        allow_store_runnable_omission=True,
        reject=_reject,
    )


def test_missing_flag_without_store_omission_rejects_unverifiable() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        require_runnable_evidence(
            {"isPublic": True},
            allow_store_runnable_omission=False,
            reject=_reject,
        )
    assert exc.value.code == "actor_runnable_unverifiable"
