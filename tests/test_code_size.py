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
    policy["frozen_files"] = []
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
    assert "src/api/server.py" in policy["frozen_files"]
    assert policy["exceptions"] == []


def test_new_oversized_python_callable_fails(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "src/example.py", _function("oversized", 151))

    files, callables = _metrics(tmp_path, policy)
    result = CODE_SIZE.evaluate(policy, files, callables, "backend")

    assert result["status"] == "failed"
    assert any("exceeds hard limit" in error for error in result["errors"])


def test_frozen_file_allows_legacy_size_without_exact_allowance(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, "src/example.py", _function("legacy", 151))
    policy["frozen_files"] = ["src/example.py"]

    files, callables = _metrics(tmp_path, policy)
    assert CODE_SIZE.evaluate(policy, files, callables, "backend")["status"] == "passed"


def test_frozen_file_growth_fails_and_shrink_needs_no_policy_change(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    policy["frozen_files"] = ["src/legacy.py"]
    _write(tmp_path, "src/legacy.py", _function("legacy", 151))
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(policy))
    base = _commit(tmp_path)

    _write(tmp_path, "src/legacy.py", _function("legacy", 152))
    growth = CODE_SIZE.compare_frozen_metrics(tmp_path, policy, base)
    assert any("frozen file grew" in error for error in growth)

    _write(tmp_path, "src/legacy.py", _function("legacy", 149))
    assert CODE_SIZE.compare_frozen_metrics(tmp_path, policy, base) == []


def test_new_oversized_callable_in_frozen_file_fails(tmp_path: Path) -> None:
    policy = _policy()
    policy["frozen_files"] = ["src/legacy.py"]
    _init_repository(tmp_path)
    _write(tmp_path, "src/legacy.py", "VALUE = 1\n")
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(policy))
    base = _commit(tmp_path)
    _write(tmp_path, "src/legacy.py", _function("new_oversized", 151))

    errors = CODE_SIZE.compare_frozen_metrics(tmp_path, policy, base)
    assert any("new callable in frozen file" in error for error in errors)


def test_release_regression_reports_all_frozen_growth_and_new_callables(tmp_path: Path) -> None:
    policy = _policy()
    paths = [
        "src/storage/service_store.py",
        "tests/test_api_service.py",
        "frontend-placeholder.py",
        "scripts/test_gate.py",
    ]
    policy["frozen_files"] = sorted(paths)
    _init_repository(tmp_path)
    for path in paths:
        _write(tmp_path, path, "VALUE = 1\n")
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(policy))
    base = _commit(tmp_path)
    _write(tmp_path, paths[0], "VALUE = 1\n" + _function("new_store_method", 151))
    _write(tmp_path, paths[1], "VALUE = 1\n" + _function("new_api_fixture", 201))
    for path in paths[2:]:
        _write(tmp_path, path, "VALUE = 1\nVALUE_2 = 2\n")

    errors = CODE_SIZE.compare_frozen_metrics(tmp_path, policy, base)

    assert len(errors) == 6
    assert sum("frozen file grew" in error for error in errors) == 4
    assert sum("new callable in frozen file" in error for error in errors) == 2


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


def test_compare_policy_rejects_limit_increase_and_new_frozen_file(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    previous = _policy()
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(previous))
    base = _commit(tmp_path)
    current = copy.deepcopy(previous)
    current["limits"]["files"]["production"]["hard"] = 801
    current["limits"]["complexity"]["target"] += 1
    current["limits"]["complexity"]["future_hard"] += 1
    current["limits"]["nesting"]["target"] += 1
    current["frozen_files"] = ["src/new.py"]

    errors = CODE_SIZE.compare_policy(tmp_path, current, base)

    assert "limits.files.production.hard cannot increase" in errors
    assert "limits.complexity.target cannot increase" in errors
    assert "limits.complexity.future_hard cannot increase" in errors
    assert "limits.nesting.target cannot increase" in errors
    assert "new frozen file is forbidden: src/new.py" in errors


def test_initial_policy_must_bind_to_trusted_base(tmp_path: Path) -> None:
    _init_repository(tmp_path)
    _write(tmp_path, "README.md", "baseline\n")
    base = _commit(tmp_path)
    policy = _policy()

    assert CODE_SIZE.compare_policy(tmp_path, policy, base) == [
        "initial policy baseline_sha must be an existing ancestor "
        f"of trusted base {base}"
    ]
    policy["baseline_sha"] = base
    assert CODE_SIZE.compare_policy(tmp_path, policy, base) == []


def test_delayed_policy_integration_accepts_ancestor_and_keeps_ratchet(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    _write(tmp_path, "README.md", "baseline\n")
    baseline = _commit(tmp_path)
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "-q", "-b", "delivery"],
        check=True,
    )
    _write(tmp_path, "release.txt", "release advanced without policy\n")
    compare_base = _commit(tmp_path, "advance delivery base")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "checkout",
            "-q",
            "-b",
            "policy-branch",
            baseline,
        ],
        check=True,
    )
    introduced = _policy()
    introduced["baseline_sha"] = baseline
    _write(tmp_path, "tests/code_size_policy.json", json.dumps(introduced))
    _commit(tmp_path, "introduce policy")
    subprocess.run(
        ["git", "-C", str(tmp_path), "checkout", "-q", "delivery"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Code Size Test",
            "-c",
            "user.email=code-size@example.invalid",
            "merge",
            "--no-ff",
            "-q",
            "-m",
            "merge delayed policy",
            "policy-branch",
        ],
        check=True,
    )

    assert CODE_SIZE.compare_policy(tmp_path, introduced, compare_base) == []

    relaxed = copy.deepcopy(introduced)
    relaxed["limits"]["files"]["production"]["hard"] += 1
    relaxed["limits"]["complexity"]["future_hard"] += 1
    relaxed["limits"]["nesting"]["target"] += 1
    relaxed["frozen_files"] = ["src/new.py"]
    errors = CODE_SIZE.compare_policy(tmp_path, relaxed, compare_base)

    assert "limits.files.production.hard cannot increase" in errors
    assert "limits.complexity.future_hard cannot increase" in errors
    assert "limits.nesting.target cannot increase" in errors
    assert "new frozen file is forbidden: src/new.py" in errors


def test_initial_policy_rejects_unknown_descendant_and_unrelated_baselines(
    tmp_path: Path,
) -> None:
    _init_repository(tmp_path)
    _write(tmp_path, "README.md", "baseline\n")
    compare_base = _commit(tmp_path)
    policy = _policy()

    policy["baseline_sha"] = "f" * 40
    assert CODE_SIZE.compare_policy(tmp_path, policy, compare_base) == [
        "initial policy baseline_sha must be an existing ancestor "
        f"of trusted base {compare_base}"
    ]

    _write(tmp_path, "later.txt", "descendant\n")
    descendant = _commit(tmp_path, "descendant")
    policy["baseline_sha"] = descendant
    assert CODE_SIZE.compare_policy(tmp_path, policy, compare_base) == [
        "initial policy baseline_sha must equal trusted base "
        f"{compare_base} or be its ancestor"
    ]

    tree = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", f"{compare_base}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    unrelated = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Code Size Test",
            "-c",
            "user.email=code-size@example.invalid",
            "commit-tree",
            tree,
            "-m",
            "unrelated root",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    policy["baseline_sha"] = unrelated
    assert CODE_SIZE.compare_policy(tmp_path, policy, compare_base) == [
        "initial policy baseline_sha must equal trusted base "
        f"{compare_base} or be its ancestor"
    ]


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
    relaxed["limits"]["complexity"]["target"] += 1
    relaxed["limits"]["nesting"]["target"] += 1

    errors = CODE_SIZE.compare_policy(tmp_path, relaxed, base)

    assert "limits.callables.production.hard cannot increase" in errors
    assert "limits.complexity.target cannot increase" in errors
    assert "limits.nesting.target cannot increase" in errors


def test_inventory_includes_untracked_but_not_ignored_source(tmp_path: Path) -> None:
    policy = _policy()
    _init_repository(tmp_path)
    _write(tmp_path, ".gitignore", "ignored.py\n")
    _write(tmp_path, "visible.py", "value = 1\n")
    _write(tmp_path, "ignored.py", _function("oversized", 151))

    files, _callables = _metrics(tmp_path, policy)

    assert [item.path for item in files] == ["visible.py"]
