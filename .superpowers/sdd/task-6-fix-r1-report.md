# Task 6 Fix R1 Report

状态：DONE

基线：`e68f03a`

## 审查项修复

- Important #1：proposal mutation 与 safe summary 成功 commit 后，`cleanup.run()` 现在位于独立 best-effort 边界；任何 cleanup 异常都会静默丢弃，不会转成 apply 失败，也不会把可能含私有路径的异常内容写入日志。
- Minor #1：新增成功 update、delete `keep`、delete `disable_private` 的 facade/apply 端到端回归，分别验证业务状态、proposal `applied`、stored summary 与 returned summary 完全一致、操作对应的精确 key 集，以及第二次 apply 稳定返回 `proposal_consumed`。

## TDD 证据

- RED：新增 4 个 apply case 后运行专项命令；update 与两种 delete 已通过，cleanup 抛错 case 按预期失败于 `src/services/agent_change_proposal.py` 的 commit 后 `cleanup.run()`，异常向调用方泄漏。
- GREEN：只为 commit 后 cleanup 增加局部 `try/except Exception`；同一专项命令 4 项全部通过。cleanup 抛错回归确认首次调用仍返回 `applied`，source/subscription/schedule、proposal 状态及 safe summary 已提交，敏感异常内容未进入捕获日志，第二次调用为 `proposal_consumed`。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py -q`：284 项通过。
- `.venv/bin/python -m pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_media_cache_unit.py -q`：36 项通过。
- `.venv/bin/python -m py_compile src/services/agent_change_proposal.py tests/test_remote_mcp_subscription_service.py`：通过。
- `python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 69.139 秒。

## 文件与范围

- `src/services/agent_change_proposal.py`
- `tests/test_remote_mcp_subscription_service.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-6-fix-r1-report.md`
- `WORKLOG.md`

未修改 Task 7+、MCP 工具注册/server wiring、UI、Skill 或生产开关。
