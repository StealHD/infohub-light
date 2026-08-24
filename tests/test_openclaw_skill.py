import json
import re
from pathlib import Path


SKILL_DIR = Path("integrations/openclaw/inteliscope")
TOOLS = {
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
    "get_source_setup_guide",
    "search_bilibili_users",
    "resolve_source",
    "list_available_sources",
    "prepare_create_subscription",
    "prepare_update_subscription",
    "prepare_delete_subscription",
    "apply_subscription_change",
    "diagnose_source",
    "diagnose_job",
    "query_operation_logs",
}
SYSTEM_SETTINGS_TOOLS = {
    "list_system_settings",
    "prepare_update_system_settings",
    "apply_system_settings_change",
}
READ_TOOLS = {
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
    "get_source_setup_guide",
    "search_bilibili_users",
    "resolve_source",
    "list_available_sources",
    "diagnose_source",
    "diagnose_job",
    "query_operation_logs",
}


def _text(path: str) -> str:
    return SKILL_DIR.joinpath(path).read_text(encoding="utf-8")


def all_skill_text() -> str:
    return "\n".join(
        _text(path)
        for path in (
            "SKILL.md",
            "README.md",
            "references/tool-contract.md",
            "references/workflows.md",
        )
    )


def test_openclaw_skill_has_required_files_frontmatter_and_mcp_dependency():
    assert {
        path.relative_to(SKILL_DIR).as_posix()
        for path in SKILL_DIR.rglob("*")
        if path.is_file()
    } == {
        "SKILL.md",
        "README.md",
        "references/tool-contract.md",
        "references/workflows.md",
    }
    skill = _text("SKILL.md")
    frontmatter = skill.split("---", 2)[1]
    assert re.search(r"(?m)^name:\s+inteliscope\s*$", frontmatter)
    assert "mcp.servers.inteliscope" in frontmatter
    assert all(
        trigger in frontmatter
        for trigger in (
            "订阅",
            "B站",
            "Bilibili",
            "UP主",
            "search_bilibili_users",
            "YouTube",
            "油管",
            "频道",
            "resolve_source",
        )
    )


def test_openclaw_skill_uses_exactly_the_subscription_contract_tools_and_no_caller_scope_input():
    combined = "\n".join(
        _text(path)
        for path in (
            "SKILL.md",
            "README.md",
            "references/tool-contract.md",
            "references/workflows.md",
        )
    )
    named_tools = set(re.findall(
        r"`(get_my_feed|get_item|list_subscriptions|source_health|list_jobs|get_job|"
        r"get_source_setup_guide|search_bilibili_users|resolve_source|list_available_sources|prepare_create_subscription|"
        r"prepare_update_subscription|prepare_delete_subscription|"
        r"apply_subscription_change|diagnose_source|diagnose_job|"
        r"query_operation_logs|list_system_settings|prepare_update_system_settings|"
        r"apply_system_settings_change)`",
        combined,
    ))
    assert named_tools == TOOLS | SYSTEM_SETTINGS_TOOLS
    assert "user_id" not in combined
    assert "workspace_id" not in combined
    assert not re.search(r"ih_mcp_v1_[A-Za-z0-9_-]{10,}", combined)
    assert "${INTELISCOPE_MCP_TOKEN}" in combined
    assert '"auth":"oauth"' not in combined
    assert "不要运行 `openclaw mcp login`" in combined


def test_openclaw_skill_defends_against_prompt_injection_and_avoids_n_plus_one_reads():
    skill = _text("SKILL.md")
    workflows = _text("references/workflows.md")
    combined = f"{skill}\n{workflows}".lower()

    assert "untrusted" in combined or "不可信" in combined
    assert "n+1" in combined
    assert "selected" in combined or "选中" in combined
    assert "令牌" in combined and "聊天" in combined
    for workflow in ("信息流", "收藏", "历史", "稍后读", "订阅", "来源健康", "任务"):
        assert workflow in combined


def test_browser_job_handoff_uses_safe_diagnosis_without_job_mutation():
    workflows = _text("references/workflows.md")

    assert "Browser handoff" in workflows
    assert "selected `job_id`" in workflows
    assert "call `diagnose_job` directly" in workflows
    assert "bounded persisted safe evidence" in workflows
    assert "never retry, cancel, modify" in workflows


def test_workspace_diagnostics_are_explicit_bounded_and_read_only():
    combined = all_skill_text()

    assert 'scope="self"' in combined
    assert 'scope="workspace"' in combined
    assert "diagnostics_scope_required" in combined
    assert "diagnostics_filter_required" in combined
    assert "minimum_level" in combined
    assert "existing connections are never upgraded" in combined
    assert "role downgrade" in combined
    assert "read-only" in combined
    assert "another user's business data" in combined


def test_skill_requires_preview_confirmation_and_never_collects_secrets():
    combined = all_skill_text().lower()
    assert "每次只询问一个" in combined
    assert "source_disposition" in combined
    assert "确认短语" in combined
    assert "prepare" in combined and "apply" in combined
    assert "最多 3" in combined
    assert "不要" in combined and "令牌" in combined and "聊天" in combined
    assert "user_id" not in combined and "workspace_id" not in combined
    assert not re.search(r"ih_mcp_v1_[a-z0-9_-]{10,}", combined)


def test_skill_change_safety_routes_existing_sources_and_web_only_setup_correctly():
    combined = all_skill_text().lower()
    assert "list_available_sources" in combined
    assert "不要推测" in combined or "never infer" in combined
    assert "apply_subscription_change 成功" in combined
    assert "article" in combined and "不能" in combined and "写入" in combined
    assert "viewer" in combined and "web" in combined and "助手连接" in combined
    assert "apify" in combined and "未预配置" in combined and "web" in combined
    assert "stale" in combined and "重新 prepare" in combined


def test_openclaw_skill_readme_documents_local_install_and_env_file_permissions():
    readme = _text("README.md")
    assert (
        "openclaw skills install ./integrations/openclaw/inteliscope "
        "--as inteliscope --force"
    ) in readme
    assert "openclaw gateway restart" in readme
    assert "openclaw skills check" in readme
    assert "~/.openclaw/.env" in readme
    assert "0600" in readme


def test_openclaw_skill_readme_uses_access_specific_tool_filters():
    configs = [
        json.loads(value)
        for value in re.findall(r"openclaw mcp set inteliscope '([^']+)'", _text("README.md"))
    ]
    assert [
        (len(config["toolFilter"]["include"]), set(config["toolFilter"]["include"]))
        for config in configs
    ] == [
        (13, READ_TOOLS),
        (17, TOOLS),
        (16, READ_TOOLS | SYSTEM_SETTINGS_TOOLS),
    ]


def test_openclaw_skill_pages_stored_article_bodies_and_fetches_the_exact_handoff_url():
    contract = _text("references/tool-contract.md")
    workflows = _text("references/workflows.md")
    combined = f"{contract}\n{workflows}"

    for field in (
        "body_offset",
        "max_body_chars",
        "body_end",
        "body_total_chars",
        "body_has_more",
        "next_body_offset",
    ):
        assert field in combined
    assert "8,000" in combined or "8000" in combined
    assert "20,000" in combined or "20000" in combined
    assert "最多三段" in combined
    assert "完整原文未保存在 Inteliscope" in combined
    assert "web_fetch exactly once" in combined
    assert "same URL" in combined or "exact URL" in combined
    assert "never search" in combined
    assert "不可信" in combined


def test_skill_uses_exact_create_envelopes_and_routes_bilibili_through_rsshub():
    skill = _text("SKILL.md")
    contract = _text("references/tool-contract.md")
    workflows = _text("references/workflows.md")
    combined = f"{skill}\n{contract}\n{workflows}"
    flattened = " ".join(combined.split())

    assert '"mode": "private"' in combined
    assert '"mode":"resolved"' in flattened
    assert '"type": "reddit"' in combined
    assert '"display_name": "r/codex"' in combined
    assert '"subreddit": "codex"' in combined
    assert "mode: create" in combined or 'mode="create"' in combined
    assert "Never" in combined and "source_type" in combined and "fields" in combined
    assert "Bilibili" in combined and "B站" in combined and "UP 主" in combined
    assert "RSSHub Base URL" in combined
    assert 'source_type="bilibili"' in combined
    assert "search_bilibili_users" in combined
    assert 'match_status="exact"' in combined
    assert "without asking the user for a UID" in combined
    assert "unsubscribed_only=false" in combined
    assert "do not prepare a duplicate" in combined
    assert '"type": "bilibili"' in combined
    assert '"route_key": "user_video"' in combined
    assert '"params": {"uid": "39627524"}' in combined
    assert "public_target" in combined
    assert "never Apify" in combined or "Never call Apify" in combined
    assert "never ask for or submit an RSSHub URL" in flattened
    assert "Cookie" in combined and "ACCESS_KEY" in combined


def test_bilibili_name_subscription_never_routes_to_browser_or_shell():
    skill = _text("SKILL.md")

    assert "must use this Skill" in skill
    assert "even when the user does" in skill
    assert "not say “Inteliscope”" in skill
    assert "never invoke Chrome" in skill
    assert "browser/browser-control tool" in skill
    assert "never ask the user to enable remote debugging" in skill
    assert "Do not ask for a Bilibili UID before calling" in skill
    assert "`search_bilibili_users`" in skill


def test_youtube_name_subscription_uses_agent_web_then_bounded_resolver():
    combined = all_skill_text()
    skill = _text("SKILL.md")

    assert "YouTube" in combined and "油管" in combined
    assert "name as sufficient discovery input" in skill
    assert "`油管`, or `频道`" not in skill
    assert "`web_search`" in combined
    assert "site:youtube.com" in combined
    assert "`resolve_source`" in combined
    assert "www.youtube.com/@…" in combined
    assert "www.youtube.com/channel/UC…" in combined
    assert "不可信" in combined or "untrusted" in combined
    assert "resolution_ref" in combined
    for status in (
        "resolved",
        "ambiguous",
        "discovery_required",
        "not_found",
        "unavailable",
        "web_setup_required",
    ):
        assert status in combined
    assert "not a channel ID or RSS URL" in combined or "not a channel ID" in combined


def test_social_profile_workflow_creates_pending_binding_without_paid_fetch():
    combined = all_skill_text()
    flattened = " ".join(combined.split())

    assert 'source_type="twitter"' in combined
    assert 'source_type="instagram"' in combined
    assert 'type="twitter"' in combined
    assert 'type="instagram"' in combined
    assert 'config={"handle"' in combined
    assert "bare `@handle`" in combined
    assert "ask which platform" in combined
    assert "pending/disabled" in combined
    assert "source_enabled=false" in combined
    assert "does not fetch data or start a paid Actor" in combined
    assert "Never automatically activate, verify, probe, fetch" in flattened
