from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_code_size", ROOT / "scripts/check_code_size.py"
)
assert SPEC and SPEC.loader
CODE_SIZE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CODE_SIZE
SPEC.loader.exec_module(CODE_SIZE)
BASE_POLICY = json.loads(
    (ROOT / "tests/code_size_policy.json").read_text(encoding="utf-8")
)


def _policy() -> dict:
    policy = copy.deepcopy(BASE_POLICY)
    policy["baseline_sha"] = "0" * 40
    policy["entrypoints"] = []
    policy["debt"] = {"files": [], "callables": []}
    return policy


def _init_repository(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def _commit(root: Path, message: str = "baseline") -> str:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Code Size Test",
            "-c",
            "user.email=code-size@example.invalid",
            "commit",
            "-q",
            "-m",
            message,
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _function(name: str, statement_count: int) -> str:
    statements = "\n".join(f"    value = {index}" for index in range(statement_count))
    return f"def {name}():\n{statements}\n"


def _metrics(root: Path, policy: dict) -> tuple[list, list]:
    return CODE_SIZE.collect_metrics(root, policy, "backend")


def _callable(policy: dict, root: Path, symbol: str):
    _files, callables = _metrics(root, policy)
    return next(item for item in callables if item.symbol == symbol)


def test_repository_policy_schema_passes() -> None:
    policy = CODE_SIZE.load_policy(ROOT / "tests/code_size_policy.json")

    assert policy["baseline_sha"] == "e10adf1a347105f4327a763ca4a84d2fe8bb34b1"
    assert policy["limits"]["files"]["production"]["hard"] == 800
    assert policy["limits"]["callables"]["production"]["hard"] == 150
    assert policy["exceptions"] == []


def test_new_oversized_python_callable_fails_without_debt(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "src/example.py", _function("oversized", 151))

    files, callables = _metrics(tmp_path, policy)
    result = CODE_SIZE.evaluate(policy, files, callables, "backend")

    assert result["status"] == "failed"
    assert any("without baseline debt" in error for error in result["errors"])


def test_callable_debt_passes_exactly_and_ratchets_on_change(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "src/example.py", _function("legacy", 151))
    metric = _callable(policy, tmp_path, "legacy")
    policy["debt"]["callables"] = [
        {
            "path": metric.path,
            "symbol": metric.symbol,
            "category": metric.category,
            "max_lines": metric.lines,
        }
    ]

    files, callables = _metrics(tmp_path, policy)
    assert CODE_SIZE.evaluate(policy, files, callables, "backend")["status"] == "passed"

    _write(tmp_path, "src/example.py", _function("legacy", 149))
    files, callables = _metrics(tmp_path, policy)
    shrink = CODE_SIZE.evaluate(policy, files, callables, "backend")
    assert any("remove obsolete debt" in error for error in shrink["errors"])

    _write(tmp_path, "src/example.py", _function("legacy", 152))
    files, callables = _metrics(tmp_path, policy)
    growth = CODE_SIZE.evaluate(policy, files, callables, "backend")
    assert any("grew from debt allowance" in error for error in growth["errors"])


def test_renamed_oversized_callable_cannot_inherit_debt(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "src/old.py", _function("legacy", 151))
    metric = _callable(policy, tmp_path, "legacy")
    policy["debt"]["callables"] = [
        {
            "path": metric.path,
            "symbol": metric.symbol,
            "category": metric.category,
            "max_lines": metric.lines,
        }
    ]
    (tmp_path / "src/old.py").unlink()
    _write(tmp_path, "src/new.py", _function("legacy", 151))

    files, callables = _metrics(tmp_path, policy)
    result = CODE_SIZE.evaluate(policy, files, callables, "backend")

    assert any("src/new.py::legacy" in error and "without baseline debt" in error for error in result["errors"])
    assert any("src/old.py::legacy" in error and "stale" in error for error in result["errors"])


def test_registered_entrypoint_uses_coordinator_limit(tmp_path: Path) -> None:
    policy = _policy()
    policy["entrypoints"] = [
        {
            "path": "src/coordinator.py",
            "symbol": "coordinate",
            "reason": "test composition root",
        }
    ]
    _init_repository(tmp_path)
    _write(tmp_path, "src/coordinator.py", _function("coordinate", 179))

    files, callables = _metrics(tmp_path, policy)
    metric = next(item for item in callables if item.symbol == "coordinate")
    result = CODE_SIZE.evaluate(policy, files, callables, "backend")

    assert metric.category == "entrypoint"
    assert metric.lines == 180
    assert result["status"] == "passed"


def test_file_debt_requires_immediate_downward_update(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "scripts/legacy.sh", "line\n" * 801)
    files, callables = _metrics(tmp_path, policy)
    metric = next(item for item in files if item.path == "scripts/legacy.sh")
    policy["debt"]["files"] = [
        {"path": metric.path, "category": metric.category, "max_lines": metric.lines}
    ]
    assert CODE_SIZE.evaluate(policy, files, callables, "backend")["status"] == "passed"

    _write(tmp_path, "scripts/legacy.sh", "line\n" * 800)
    files, callables = _metrics(tmp_path, policy)
    result = CODE_SIZE.evaluate(policy, files, callables, "backend")

    assert any("remove obsolete debt allowance" in error for error in result["errors"])


def test_policy_rejects_nonempty_exceptions(tmp_path: Path) -> None:
    policy = _policy()
    policy["exceptions"] = [{"path": "src/example.py"}]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    try:
        CODE_SIZE.load_policy(path)
    except CODE_SIZE.PolicyError as exc:
        assert "exceptions are not permitted" in str(exc)
    else:
        raise AssertionError("nonempty exceptions must fail")


def test_compare_policy_rejects_limit_increase_and_new_debt(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    previous = _policy()
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(previous))
    base = _commit(tmp_path)
    current = copy.deepcopy(previous)
    current["limits"]["files"]["production"]["hard"] = 801
    current["debt"]["files"] = [
        {"path": "src/new.py", "category": "production", "max_lines": 900}
    ]

    errors = CODE_SIZE.compare_policy(tmp_path, current, base)

    assert "limits.files.production.hard cannot increase" in errors
    assert "new file debt is forbidden: src/new.py" in errors


def test_initial_policy_must_bind_to_trusted_base(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _write(tmp_path, "README.md", "baseline\n")
    base = _commit(tmp_path)
    policy = _policy()

    assert CODE_SIZE.compare_policy(tmp_path, policy, base) == [
        f"initial policy baseline_sha must equal trusted base {base}"
    ]
    policy["baseline_sha"] = base
    assert CODE_SIZE.compare_policy(tmp_path, policy, base) == []


def test_bootstrap_branch_policy_prevents_later_relaxation(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _write(tmp_path, "README.md", "baseline\n")
    base = _commit(tmp_path)
    introduced = _policy()
    introduced["baseline_sha"] = base
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(introduced))
    _commit(tmp_path, "introduce policy")
    relaxed = copy.deepcopy(introduced)
    relaxed["limits"]["callables"]["production"]["hard"] += 1

    errors = CODE_SIZE.compare_policy(tmp_path, relaxed, base)

    assert "limits.callables.production.hard cannot increase" in errors


def test_inventory_includes_untracked_but_not_ignored_source(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, ".gitignore", "ignored.py\n")
    _write(tmp_path, "visible.py", "value = 1\n")
    _write(tmp_path, "ignored.py", _function("oversized", 151))

    files, _callables = _metrics(tmp_path, policy)

    assert [item.path for item in files] == ["visible.py"]
