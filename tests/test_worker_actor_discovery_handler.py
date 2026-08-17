from __future__ import annotations

from src.services.secret_store import SecretStore
from src.services.worker_actor_discovery_handler import _metadata_token


def test_discovery_metadata_token_reads_runtime_secret_store(tmp_path) -> None:
    SecretStore(tmp_path).set("TEST_ACTOR_DISCOVERY_TOKEN", "runtime-secret")

    assert (
        _metadata_token(str(tmp_path), "TEST_ACTOR_DISCOVERY_TOKEN")
        == "runtime-secret"
    )
