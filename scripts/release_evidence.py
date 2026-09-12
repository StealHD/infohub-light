"""Check reusable local Gate coverage for the complete deployment delta."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.release_mode import git
from scripts.test_gate_changes import GateConfigError, build_plan, load_mapping
from scripts.test_gate_ci import _force_full
from scripts.test_gate_commands import build_command_specs
from scripts.test_gate_evidence import environment, inputs, normalized


def required_plan(root: Path, baseline: str | None) -> tuple[dict, dict]:
    mapping = load_mapping(root / "tests/test_impact_map.json")
    if baseline:
        subprocess.run(["git", "merge-base", "--is-ancestor", baseline, "HEAD"],
                       cwd=root, check=True, capture_output=True)
        changed = git(root, "diff", "--name-only", "--no-renames", "-z", baseline, "HEAD", "--").split("\0")
    else:
        changed = []
    plan = build_plan([p for p in changed if p], mapping)
    plan.update(base_sha=baseline, head_sha=git(root, "rev-parse", "HEAD"))
    if not baseline:
        _force_full(plan, "unknown production baseline requires complete local evidence")
    return plan, mapping


def read_passed(root: Path, path: Path) -> tuple[dict, dict[str, list[str]]]:
    result = json.loads(path.read_text())
    if not isinstance(result, dict) or not isinstance(result.get("verification"), dict):
        raise GateConfigError("missing or malformed local Gate evidence")
    evidence = result.get("verification", {})
    current = inputs(root)
    # A mapping miss forces the Gate to full coverage.  Once that complete
    # Gate has passed, rejecting its evidence here would make fast releases
    # impossible for safely fail-closed, newly mapped code.
    if (result.get("status") != "passed"
            or evidence.get("schema") != 1 or not evidence.get("reusable")
            or evidence.get("inputs", {}).get("source") != current["source"]
            or evidence.get("environment") != environment()):
        raise GateConfigError("missing, stale or incompatible local Gate evidence")
    commands = result.get("commands", [])
    passed = {c["command_id"] for c in commands if c.get("exit_code") == 0
              and not c.get("unclosed_sqlite_connection_warnings")}
    specs = evidence.get("specs", [])
    if (len(commands) != len(passed) or len(specs) != len(passed)
            or {s["id"] for s in specs} != passed):
        raise GateConfigError("incomplete local Gate execution")
    return result, {s["id"]: s["argv"] for s in specs}


def covers(spec, actual: dict[str, list[str]], root: Path) -> bool:
    wanted = normalized(spec.argv, root)
    identifier = spec.command_id
    aliases = {"python_targeted": "python_full", "python_changed_syntax": "python_syntax",
               "frontend_related": "frontend_vitest", "frontend_typecheck": "frontend_build"}
    if aliases.get(identifier) in actual:
        return True
    got = actual.get(identifier)
    if got is None:
        return False
    if identifier.startswith("code_size_"):
        return got[:4] == wanted[:4]
    if identifier == "e2e_contract" and len(got) == 2:
        return True
    if identifier == "release_playwright" and got == ["npm", "run", "e2e:release"]:
        return True
    if identifier in {"python_targeted", "python_changed_syntax", "frontend_related", "release_playwright", "e2e_contract"}:
        if identifier == "release_playwright" and "--" not in wanted:
            return got == wanted
        return set(wanted) <= set(got)
    return wanted == got


def validate(root: Path, gate: Path, e2e: Path | None, baseline: str | None) -> dict[str, Any]:
    plan, mapping = required_plan(root, baseline)
    _, actual = read_passed(root, gate)
    specs = build_command_specs(root, plan, mapping, mode="preflight")
    missing = [s.command_id for s in specs if s.domain != "control" and not covers(s, actual, root)]
    if plan.get("ui_impacted"):
        browser = read_passed(root, e2e)[1] if e2e else actual
        required = build_command_specs(root, plan, mapping, mode="release", scope="e2e", skip_control=True)
        missing.extend(s.command_id for s in required if not covers(s, browser, root))
    if missing:
        selector = f"--base {baseline} --head HEAD" if baseline else "--mode full"
        code = f"python scripts/test_gate.py preflight {selector}" if baseline else "python scripts/test_gate.py run --mode full"
        browser_command = (f"python scripts/test_gate.py run --mode release --scope e2e "
                           + (f"--base {baseline} --head HEAD" if baseline else "--full-e2e"))
        raise GateConfigError(f"missing coverage: {', '.join(missing)}; run {code}; UI: {browser_command}")
    return {"inputs": inputs(root), "baseline": baseline, "plan": plan,
            "gate_result": str(gate.resolve()), "e2e_result": str(e2e.resolve()) if e2e else None}
