# Task 7 Fix R5 Report

状态：DONE

基线：`b3e286e`

## 第五轮审查项修复

- `JobQueue.retry_job()` 的 terminal-to-queued 条件 UPDATE 现在于同一事务清除上一 attempt 的 `result_json` 与 `started_at`；下一次 claim 会写入当前 attempt 的开始时间。
- R4 的 Health application ledger 删除与 `last_job_id` 断开顺序保持不变，并继续位于 Job 条件 UPDATE 成功之后。权限失败、非 terminal、返回另一 active Job、`commit=False` 回滚与并发语义不变。
- 其余字段已按状态机逐项核验：`attempts`、terminal/error/claim/lease 字段原本已重置；`created_at/payload/priority/max_attempts/next_run_at/expires_at` 是同一 Job 的持久属性，没有证据需要清除。

## TDD 证据

- RED：caller-owned transaction 回归与真实 Worker 回归 2/2 精确失败；retry 后仍分别读到旧的 `fetched_count/run_status/snapshot_id` summary。
- GREEN：仅增加 `result_json=NULL` 与 `started_at=NULL` 后专项 2/2 通过。
- 真实 Worker 路径覆盖首轮 `partial` 产生 `fetched_count=1/run_status=partial/snapshot_id`，manual retry 后分别观察 `queued` 与 `running`，再令第二次 attempt 在 `FeedRunResult` 前抛出 job-level `RuntimeError`。该异常以 `result=None` 进入 `fail_or_retry_job()` 并最终 `failed`；普通 `list_jobs/get_job` 与 `diagnose_job/diagnose_source` 在三个阶段均无旧 result summary。
- caller-owned transaction 回归同时证明 attempt-local Job 字段、R4 ledger 与 Health FK 可整体回滚。

## 验证

- job queue/reliability/Worker/diagnostics/read/Source Health focused：288 项通过。
- R4 API/MCP/schedule/reliability/Source Health Worker 邻接 11 文件：238 项通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 77.27 秒。
- `.venv/bin/python -m py_compile ...`、`python3 -m json.tool project-defaults.yaml`、`python3 -m json.tool tests/test_impact_map.json` 与 `git diff --check`：通过。

## 文件与范围

- `src/services/job_queue.py`
- `tests/test_job_queue.py`
- `tests/test_remote_mcp_diagnostics.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-7-fix-r5-report.md`
- `WORKLOG.md`

Task 8+ 的 MCP 注册/server wiring、UI、OpenClaw Skill、生产开关与 canary 均未实现。
