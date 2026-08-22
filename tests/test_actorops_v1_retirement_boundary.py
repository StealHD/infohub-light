"""Ratchet ActorOps v1 references out of the online runtime."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "tests" / "actorops_v1_runtime_allowlist.json"

SCAN_ROOTS = (
    "src/api",
    "src/services",
    "src/scrapers/apify_social.py",
    "src/orchestrator.py",
    "frontend/src/features/settings/SettingsActorOpsPage.tsx",
    "frontend/src/features/apify-actors",
    "frontend/src/api",
)

TOKENS = {
    "runtime": (
        "ApifyActorOpsService",
        "ActorOpsCompatibilityService",
        "build_apify_actor_route",
        "apify_actor_ops_for",
    ),
    "jobs": (
        "apify_actor_discovery",
        "apify_actor_validation",
        "apify_actor_canary_batch",
        "apify_actor_freshness_check",
    ),
    "tables": (
        "apify_actor_routes",
        "apify_actor_candidates",
        "apify_actor_attempts",
        "apify_actor_target_health",
        "apify_actor_route_profiles",
        "apify_actor_adapter_revisions",
        "apify_route_active_slots",
        "apify_actor_metadata_observations",
        "apify_source_route_bindings",
        "apify_actor_discovery_runs",
        "apify_actor_discovery_run_revisions",
        "apify_actor_discovery_settings",
        "apify_actor_validations",
        "apify_actor_canary_batches",
        "apify_actor_canary_batch_items",
        "apify_actor_pool_stages",
        "apify_actor_pool_stage_sources",
        "apify_actor_pool_stage_candidate_settings",
        "apify_actor_freshness_checks",
        "apify_actor_freshness_results",
        "apify_actor_evaluation_history",
        "apify_actor_diagnostic_events",
        "apify_actor_auto_pool_runs",
    ),
    "frontend": (
        "HeroActorOpsControlPlane",
        "HeroApifyActorRouteSettings",
        "ActorOpsPoolManagementControls",
        "ActorOpsWorkflowDialogs",
        "useActorOpsPoolCandidates",
        "useActorOpsPoolManagement",
        "useActorOpsVerifiedActivation",
        "actorOpsSourceCanary",
    ),
}


def _source_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in SCAN_ROOTS:
        target = root / relative
        if target.is_file():
            files.append(target)
        elif target.exists():
            files.extend(
                path
                for path in target.rglob("*")
                if path.suffix in {".py", ".ts", ".tsx"}
            )
    return tuple(files)


def _findings(root: Path) -> dict[str, list[str]]:
    findings = {group: [] for group in TOKENS}
    for path in _source_files(root):
        content = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(root).as_posix()
        for group, tokens in TOKENS.items():
            if any(token in content for token in tokens):
                findings[group].append(relative)
    return {
        group: sorted(set(paths))
        for group, paths in findings.items()
    }


def test_actorops_v1_runtime_references_only_shrink() -> None:
    expected = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    assert _findings(ROOT) == expected


def test_actorops_v1_boundary_scanner_detects_new_reference(tmp_path: Path) -> None:
    source = tmp_path / "src" / "api"
    source.mkdir(parents=True)
    (source / "new_route.py").write_text(
        "from src.services.apify_actor_ops import ApifyActorOpsService\n",
        encoding="utf-8",
    )
    findings = _findings(tmp_path)
    assert findings["runtime"] == ["src/api/new_route.py"]
