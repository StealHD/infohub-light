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
    "list_available_sources",
    "prepare_create_subscription",
    "prepare_update_subscription",
    "prepare_delete_subscription",
    "apply_subscription_change",
    "diagnose_source",
    "diagnose_job",
}
READ_TOOLS = {
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
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
        r"get_source_setup_guide|list_available_sources|prepare_create_subscription|"
        r"prepare_update_subscription|prepare_delete_subscription|"
        r"apply_subscription_change|diagnose_source|diagnose_job)`",
        combined,
    ))
    assert named_tools == TOOLS
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
    assert "openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope" in readme
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
    ] == [(6, READ_TOOLS), (14, TOOLS)]
