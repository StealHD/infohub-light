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
}


def _text(path: str) -> str:
    return SKILL_DIR.joinpath(path).read_text(encoding="utf-8")


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


def test_openclaw_skill_uses_exactly_six_read_only_tools_and_no_caller_scope_input():
    combined = "\n".join(
        _text(path)
        for path in (
            "SKILL.md",
            "README.md",
            "references/tool-contract.md",
            "references/workflows.md",
        )
    )
    named_tools = set(re.findall(r"`(get_my_feed|get_item|list_subscriptions|source_health|list_jobs|get_job)`", combined))
    assert named_tools == TOOLS
    assert "user_id" not in combined
    assert "workspace_id" not in combined
    assert "read-only" in combined.lower() or "只读" in combined
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


def test_openclaw_skill_readme_documents_local_install_and_env_file_permissions():
    readme = _text("README.md")
    assert "openclaw skills install ./integrations/openclaw/inteliscope --as inteliscope" in readme
    assert "openclaw skills check" in readme
    assert "~/.openclaw/.env" in readme
    assert "0600" in readme
