"""Static cross-checks against the actual split Worker dispatch and policies."""

from __future__ import annotations

import ast
from pathlib import Path


def _assignments(tree: ast.Module) -> dict[str, ast.AST]:
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            values[node.target.id] = node.value
    return values


def _strings(node: ast.AST, names: dict[str, ast.AST]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name) and node.id in names:
        return _strings(names[node.id], {k: v for k, v in names.items() if k != node.id})
    if isinstance(node, ast.Starred):
        return _strings(node.value, names)
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return set().union(*(_strings(item, names) for item in node.elts))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
        return _strings(node.args[0], names)
    raise ValueError("Worker type declaration cannot be statically checked")


def _dict_keys(node: ast.AST, *, allow_unpack: bool = False) -> set[str]:
    if not isinstance(node, ast.Dict):
        raise ValueError("Worker registry must use an explicit dictionary")
    if any(not (isinstance(key, ast.Constant) and isinstance(key.value, str))
           for key in node.keys if not (allow_unpack and key is None)):
        raise ValueError("Worker registry keys must be explicit strings")
    return {key.value for key in node.keys if isinstance(key, ast.Constant)}


def check_worker_registry(root: Path) -> list[str]:
    """No imports, execution, credentials or runtime initialization in this gate."""
    try:
        trees = {
            name: ast.parse((root / f"src/services/{name}.py").read_text())
            for name in ("worker", "worker_handlers", "worker_job_policy", "worker_actorops_v2_jobs")
        }
        policy_names = _assignments(trees["worker_job_policy"])
        claimable = _strings(policy_names["WORKER_CLAIMABLE_JOB_TYPES"], policy_names)
        actor_tree = trees["worker_actorops_v2_jobs"]
        actor_policy = _dict_keys(_assignments(actor_tree)["_TRACE_POLICY"])
        actor_handlers = set()
        for node in ast.walk(actor_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript):
                        actor_handlers |= _strings(target.slice, {})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                actor_handlers |= _dict_keys(node.args[0])
        policy_node = _assignments(trees["worker"])["WORKER_JOB_TRACE_POLICY"]
        policy = _dict_keys(policy_node, allow_unpack=True)
        if not isinstance(policy_node, ast.Dict) or not any(
            key is None and isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "actorops_v2_job_trace_policy"
            for key, value in zip(policy_node.keys, policy_node.values)
        ):
            return ["Worker trace policy must include the ActorOps trace policy"]
        policy |= actor_policy
        dispatched = set(actor_handlers)
        for node in ast.walk(trees["worker_handlers"]):
            if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name) or node.left.id != "job_type":
                continue
            if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.In)):
                dispatched |= _strings(node.comparators[0], {})
        errors = []
        if not dispatched or claimable != dispatched or policy != dispatched:
            errors.append(f"claimable={sorted(claimable)} dispatch={sorted(dispatched)} trace={sorted(policy)} must agree")
        if actor_handlers != actor_policy:
            errors.append("ActorOps handler registry and trace policy disagree")
        return errors
    except (OSError, SyntaxError, ValueError, KeyError, IndexError):
        return ["Worker registry cannot be statically checked; update the contract checker"]
