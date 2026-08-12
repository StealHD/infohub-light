from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_markdown_controls", ROOT / "scripts/check_markdown_controls.py"
)
assert SPEC and SPEC.loader
CONTROLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLS)
LEGACY_AUTHORITY = "API" + "_CONTRACT.md"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_control_tree(root: Path) -> None:
    _write(
        root,
        "AGENTS.md",
        "docs/contracts/api/ docs/contracts/architecture/ docs/contracts/ui/ docs/decisions/ 任务读取路由\n",
    )
    _write(root, "PLAN.md", "# Plan\n")
    _write(root, "WORKLOG.md", "# Worklog\n")
    for relative in (
        "docs/contracts/api/README.md",
        "docs/contracts/architecture/README.md",
        "docs/contracts/ui/README.md",
    ):
        _write(root, relative, "# Index\n")
    _write(
        root,
        "docs/decisions/README.md",
        "| ID | 标题 | 日期 | 记录 |\n| --- | --- | --- | --- |\n| D001 | Test | 2026-08-07 | [查看](records/D001-D025.md#d001) |\n",
    )
    _write(
        root,
        "docs/decisions/records/D001-D025.md",
        "# Records\n\n<a id=\"d001\"></a>\n### D001 Test\n- 决策日期：2026-08-07\n",
    )


def _init_repository(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)


def test_repository_markdown_controls_pass():
    assert CONTROLS.validate(ROOT) == []


def test_markdown_controls_reject_duplicate_decision_and_large_plan(tmp_path: Path):
    _minimal_control_tree(tmp_path)
    _init_repository(tmp_path)
    record = tmp_path / "docs/decisions/records/D001-D025.md"
    record.write_text(record.read_text(encoding="utf-8") + "\n### D001 Duplicate\n", encoding="utf-8")
    (tmp_path / "PLAN.md").write_text("x" * (12 * 1024 + 1), encoding="utf-8")

    errors = CONTROLS.validate(tmp_path)

    assert any("decision IDs must be unique" in error for error in errors)
    assert any("PLAN exceeds" in error for error in errors)


def test_markdown_controls_ignore_operator_owned_ignored_files(tmp_path: Path):
    _minimal_control_tree(tmp_path)
    _write(tmp_path, ".gitignore", ".superpowers/\n")
    _init_repository(tmp_path)
    _write(tmp_path, ".superpowers/sdd/local.md", f"{LEGACY_AUTHORITY}\n")

    assert CONTROLS.validate(tmp_path) == []


def test_markdown_controls_scan_non_ignored_untracked_files(tmp_path: Path):
    _minimal_control_tree(tmp_path)
    _init_repository(tmp_path)
    _write(tmp_path, "local-notes.md", f"{LEGACY_AUTHORITY}\n")

    errors = CONTROLS.validate(tmp_path)

    assert any(
        f"local-notes.md: obsolete authority reference {LEGACY_AUTHORITY}" in error
        for error in errors
    )


def test_markdown_controls_scan_tracked_files_even_when_later_ignored(tmp_path: Path):
    _minimal_control_tree(tmp_path)
    _write(tmp_path, "tracked-notes.md", f"{LEGACY_AUTHORITY}\n")
    _init_repository(tmp_path)
    _write(tmp_path, ".gitignore", "tracked-notes.md\n")

    errors = CONTROLS.validate(tmp_path)

    assert any(
        f"tracked-notes.md: obsolete authority reference {LEGACY_AUTHORITY}" in error
        for error in errors
    )


def test_markdown_controls_fail_closed_outside_git_repository(tmp_path: Path):
    _minimal_control_tree(tmp_path)

    errors = CONTROLS.validate(tmp_path)

    assert len(errors) == 1
    assert errors[0].startswith("repository inventory failed")
