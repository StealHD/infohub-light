from __future__ import annotations

from scripts import setup_openclaw_local


def test_setup_entrypoint_keeps_its_compatibility_surface() -> None:
    required = {
        "FULL_TOOL_FILTER",
        "LEGACY_FULL_TOOL_FILTER",
        "LEGACY_READ_TOOL_FILTER",
        "MANAGED_COMMENT",
        "READ_TOOL_FILTER",
        "CommandRunner",
        "GatewayInfo",
        "SetupError",
        "build_parser",
        "compose_image_from_ps",
        "default_origin",
        "main",
        "merge_allowed_origins",
        "parse_gateway_status",
        "run_setup",
        "skill_tree_matches",
        "standard_tool_filter_upgrade",
        "update_env_text",
        "validate_gateway_url",
        "validate_origin",
    }

    assert required <= set(vars(setup_openclaw_local))
