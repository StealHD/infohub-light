from __future__ import annotations

from src.services.actorops.apify_catalog_credentials import (
    resolve_apify_catalog_credential,
)
from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _credential(
    store: ServiceStore,
    secrets: SecretStore,
    service: ApifyKeyPoolService,
    *,
    suffix: str,
) -> dict:
    env_name = f"ACTOROPS_CATALOG_TEST_{suffix}"
    ref = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=None,
        name=f"Catalog {suffix}",
        env_name=env_name,
        kind="provider",
        provider="apify",
    )
    secrets.set(env_name, f"private-{suffix.casefold()}-token")
    service.append_secret(str(ref["id"]))
    return ref


def _pool(tmp_path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    secrets = SecretStore(store.data_dir)
    service = ApifyKeyPoolService(store, secret_store=secrets)
    return store, secrets, service


def test_validation_catalog_resolves_dedicated_key_without_active_acquisition(
    tmp_path,
) -> None:
    store, secrets, service = _pool(tmp_path)
    acquisition = _credential(store, secrets, service, suffix="ACQUISITION")
    validation = _credential(store, secrets, service, suffix="VALIDATION")
    service.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=str(validation["id"]),
        expected_generation=service.current_generation(DEFAULT_WORKSPACE_ID),
    )
    store.connect().execute(
        """UPDATE apify_key_pool_members SET status='invalid'
             WHERE workspace_id=? AND secret_id=?""",
        (DEFAULT_WORKSPACE_ID, str(acquisition["id"])),
    )
    store.connect().execute(
        """UPDATE apify_key_pool_state
              SET status='exhausted', active_secret_id=NULL
            WHERE workspace_id=?""",
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().commit()

    resolved = resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="validation",
    )

    assert resolved is not None
    assert resolved.role == "validation"
    assert resolved.env_name == "ACTOROPS_CATALOG_TEST_VALIDATION"
    assert resolved.token == "private-validation-token"
    assert resolved.token not in repr(resolved)
    store.close()


def test_validation_catalog_falls_back_to_active_acquisition_key(tmp_path) -> None:
    store, secrets, service = _pool(tmp_path)
    _credential(store, secrets, service, suffix="ACQUISITION")

    resolved = resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="validation",
    )

    assert resolved is not None
    assert resolved.role == "acquisition"
    assert resolved.token == "private-acquisition-token"

    discovery = resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="acquisition",
    )
    assert discovery is not None
    assert discovery.role == "acquisition"
    assert discovery.token == "private-acquisition-token"
    store.close()


def test_catalog_credential_is_unavailable_when_pool_has_no_usable_key(
    tmp_path,
) -> None:
    store, _secrets, _service = _pool(tmp_path)

    assert resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="validation",
    ) is None
    assert resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="acquisition",
    ) is None
    store.close()


def test_validation_catalog_does_not_bypass_unusable_dedicated_key(
    tmp_path,
) -> None:
    store, secrets, service = _pool(tmp_path)
    _credential(store, secrets, service, suffix="ACQUISITION")
    validation = _credential(store, secrets, service, suffix="VALIDATION")
    service.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=str(validation["id"]),
        expected_generation=service.current_generation(DEFAULT_WORKSPACE_ID),
    )
    secrets.delete("ACTOROPS_CATALOG_TEST_VALIDATION")

    assert resolve_apify_catalog_credential(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=str(store.data_dir),
        purpose="validation",
    ) is None
    store.close()
