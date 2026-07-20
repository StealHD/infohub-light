from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.services.secret_store import SecretStore, SecretValueError


def test_secret_store_writes_mode_0600_and_never_exposes_values_in_status(tmp_path) -> None:
    store = SecretStore(tmp_path)

    store.set("GOOGLE_API_KEY", "google-secret-value")

    path = tmp_path / "secrets.env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.status("GOOGLE_API_KEY") == {"env_name": "GOOGLE_API_KEY", "is_set": True}
    assert "google-secret-value" not in repr(store.status("GOOGLE_API_KEY"))


def test_secret_store_reloads_rotated_values_without_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    store = SecretStore(tmp_path)
    store.set("APIFY_TOKEN", "first-value")
    store.load_into_environ()
    assert os.environ["APIFY_TOKEN"] == "first-value"

    store.set("APIFY_TOKEN", "second-value")
    store.load_into_environ()

    assert os.environ["APIFY_TOKEN"] == "second-value"


def test_secret_store_concurrent_writes_preserve_every_key(tmp_path) -> None:
    store = SecretStore(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: store.set(f"APIFY_TOKEN_{index}", f"value-{index}"), range(20)))

    values = store.read()
    assert values == {f"APIFY_TOKEN_{index}": f"value-{index}" for index in range(20)}
    assert not list(tmp_path.glob(".secrets.env.*.tmp"))


@pytest.mark.parametrize("env_name", ["", "not-valid", "1INVALID", "HAS SPACE"])
def test_secret_store_rejects_invalid_environment_names(tmp_path, env_name) -> None:
    with pytest.raises(SecretValueError):
        SecretStore(tmp_path).set(env_name, "value")


@pytest.mark.parametrize("value", ["", "line1\nline2", "bad\x00value"])
def test_secret_store_rejects_empty_or_multiline_values(tmp_path, value) -> None:
    with pytest.raises(SecretValueError):
        SecretStore(tmp_path).set("GOOGLE_API_KEY", value)


def test_secret_store_delete_removes_value_from_file_and_managed_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    store = SecretStore(tmp_path)
    store.set("GOOGLE_API_KEY", "temporary-value")
    store.load_into_environ()

    store.delete("GOOGLE_API_KEY")
    store.load_into_environ()

    assert "GOOGLE_API_KEY" not in store.read()
    assert "GOOGLE_API_KEY" not in os.environ
