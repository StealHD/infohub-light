from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.system_settings import (
    SystemSettingsGenerationConflict,
    SystemSettingsService,
    resolve_system_setting,
)
from src.services.system_settings_proposals import (
    SystemSettingProposalError,
    SystemSettingProposalService,
    SystemSettingsActor,
)
from src.services.system_settings_registry import (
    MANAGED_SYSTEM_SETTING_ENV_NAMES,
    SYSTEM_SETTING_DEFINITIONS,
    InvalidSystemSetting,
    canonical_setting_key,
)
from src.services.quota import QuotaExceeded, QuotaService
from src.services.worker_schedule_gate import (
    enabled_schedule_workspace_ids,
    worker_schedule_polling_enabled,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from src.storage.system_settings_v32_schema import (
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)


def _context(tmp_path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="settings-owner",
        password="safe-test-password",
        role="owner",
    )
    actor = SystemSettingsActor(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=owner["id"],
        channel="web",
    )
    return store, actor


def test_registry_has_exact_typed_allowlist_and_aliases() -> None:
    assert len(SYSTEM_SETTING_DEFINITIONS) == 21
    assert len(MANAGED_SYSTEM_SETTING_ENV_NAMES) == 21
    assert SYSTEM_SETTING_DEFINITIONS["acquisition.shared_enabled"].default is True
    assert canonical_setting_key(
        "INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY"
    ) == "limits.max_workspace_fetch_attempts_per_day"
    with pytest.raises(InvalidSystemSetting):
        canonical_setting_key("DATABASE_URL")


def test_fresh_store_bootstraps_global_32_and_workspace_row(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()

    assert migration_marker_exists(connection)
    assert schema_shapes_valid(connection)
    row = connection.execute(
        """SELECT generation, overrides_json FROM workspace_system_settings
           WHERE workspace_id=?""",
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert tuple(row) == (1, "{}")
    assert connection.execute(
        "SELECT name FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()[0] == "workspace_system_settings"


def test_resolver_prefers_override_then_environment_then_default(tmp_path, monkeypatch) -> None:
    store, _ = _context(tmp_path)
    key = "limits.max_workspace_fetch_attempts_per_day"
    monkeypatch.setenv("INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY", "250")
    assert resolve_system_setting(store, DEFAULT_WORKSPACE_ID, key) == 250

    store.connect().execute(
        """UPDATE workspace_system_settings
           SET overrides_json=?, generation=2 WHERE workspace_id=?""",
        (json.dumps({key: 500}), DEFAULT_WORKSPACE_ID),
    )
    store.connect().commit()
    assert resolve_system_setting(store, DEFAULT_WORKSPACE_ID, key) == 500
    listed = SystemSettingsService(store).list_settings(DEFAULT_WORKSPACE_ID)
    item = next(setting for setting in listed["settings"] if setting["key"] == key)
    assert item["fallback_value"] == 250


def test_runtime_consumers_observe_database_overrides_without_restart(tmp_path) -> None:
    store, actor = _context(tmp_path)
    proposals = SystemSettingProposalService(store)
    prepared = proposals.prepare(
        actor,
        expected_generation=1,
        changes={
            "limits.max_workspace_fetch_attempts_per_day": 0,
            "scheduling.automatic_enqueue_enabled": False,
        },
    )
    proposals.apply(
        actor,
        proposal_id=prepared["proposal_id"],
        confirmation=prepared["confirmation"],
    )

    with pytest.raises(QuotaExceeded, match="workspace fetch attempt"):
        QuotaService(store).admit_fetch_attempt(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=actor.user_id,
            provider="rss",
        )
    assert worker_schedule_polling_enabled(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ) is False
    assert enabled_schedule_workspace_ids(store) == ()


def test_managed_environment_names_are_centralized_in_registry() -> None:
    source_root = Path(__file__).parents[1] / "src"
    registry = source_root / "services" / "system_settings_registry.py"
    offenders = []
    for path in source_root.rglob("*.py"):
        if path == registry:
            continue
        text = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.relative_to(source_root)}:{name}"
            for name in MANAGED_SYSTEM_SETTING_ENV_NAMES
            if name in text
        )
    assert offenders == []


def test_preview_validates_cross_setting_invariant_and_warns_about_caps(tmp_path) -> None:
    store, _ = _context(tmp_path)
    service = SystemSettingsService(store)

    preview = service.preview(
        DEFAULT_WORKSPACE_ID,
        expected_generation=1,
        changes={"INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY": 500},
    )
    assert preview["changes"] == {
        "limits.max_workspace_fetch_attempts_per_day": 500
    }
    assert "workspace fetch capacity exceeds" in preview["warnings"][0]

    with pytest.raises(InvalidSystemSetting):
        service.preview(
            DEFAULT_WORKSPACE_ID,
            expected_generation=1,
            changes={
                "acquisition.min_ttl_minutes": 90,
                "acquisition.fallback_ttl_minutes": 30,
            },
        )


def test_web_proposal_requires_exact_confirmation_and_is_single_use(tmp_path) -> None:
    store, actor = _context(tmp_path)
    proposals = SystemSettingProposalService(store)
    prepared = proposals.prepare(
        actor,
        expected_generation=1,
        changes={"INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY": 500},
    )
    row = store.connect().execute(
        "SELECT confirmation_hash, preview_json FROM system_setting_change_proposals"
    ).fetchone()
    assert prepared["confirmation"] not in str(row["preview_json"])
    assert prepared["confirmation"] != row["confirmation_hash"]

    with pytest.raises(SystemSettingProposalError) as error:
        proposals.apply(
            actor, proposal_id=prepared["proposal_id"], confirmation="确认执行 wrong"
        )
    assert error.value.code == "system_settings_confirmation_mismatch"

    result = proposals.apply(
        actor,
        proposal_id=prepared["proposal_id"],
        confirmation=prepared["confirmation"],
    )
    assert result["generation"] == 2
    assert resolve_system_setting(
        store, DEFAULT_WORKSPACE_ID,
        "INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY",
    ) == 500
    with pytest.raises(SystemSettingProposalError) as error:
        proposals.apply(
            actor,
            proposal_id=prepared["proposal_id"],
            confirmation=prepared["confirmation"],
        )
    assert error.value.code == "system_settings_proposal_not_pending"


def test_apply_rejects_generation_change_and_disabled_admin(tmp_path) -> None:
    store, actor = _context(tmp_path)
    proposals = SystemSettingProposalService(store)
    prepared = proposals.prepare(
        actor,
        expected_generation=1,
        changes={"jobs.max_attempts": 4},
    )
    store.connect().execute(
        "UPDATE workspace_system_settings SET generation=2 WHERE workspace_id=?",
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().commit()
    with pytest.raises(SystemSettingsGenerationConflict):
        proposals.apply(
            actor,
            proposal_id=prepared["proposal_id"],
            confirmation=prepared["confirmation"],
        )

    store.connect().execute(
        "UPDATE workspace_system_settings SET generation=1 WHERE workspace_id=?",
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().execute("UPDATE users SET enabled=0 WHERE id=?", (actor.user_id,))
    store.connect().commit()
    with pytest.raises(SystemSettingProposalError) as error:
        proposals.apply(
            actor,
            proposal_id=prepared["proposal_id"],
            confirmation=prepared["confirmation"],
        )
    assert error.value.code == "system_settings_admin_required"


def test_apply_revalidates_dependencies_against_current_fallbacks(
    tmp_path, monkeypatch
) -> None:
    store, actor = _context(tmp_path)
    proposals = SystemSettingProposalService(store)
    prepared = proposals.prepare(
        actor,
        expected_generation=1,
        changes={"acquisition.min_ttl_minutes": 20},
    )
    monkeypatch.setenv("HORIZON_SHARED_ACQUISITION_FALLBACK_TTL_MINUTES", "10")

    with pytest.raises(InvalidSystemSetting):
        proposals.apply(
            actor,
            proposal_id=prepared["proposal_id"],
            confirmation=prepared["confirmation"],
        )

    assert SystemSettingsService(store).state(DEFAULT_WORKSPACE_ID)[1] == 1
