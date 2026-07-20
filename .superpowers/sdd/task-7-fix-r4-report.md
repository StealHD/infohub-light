# Task 7 Fix R4 Report

状态：DONE

基线：`822dc82`

## 第四轮审查项修复

- `JobQueue.retry_job()` 只有在目标 terminal Job 成功原地转为 `queued` 后，才在同一事务删除该 Job 的全部 `user_source_health_applications`，并把仍指向该 Job 的 `user_source_health.last_job_id` 置空；旧 status、计数、issue 与时间继续保留为历史状态。
- 新 attempt 的 Worker `SourceOutcome` 因此可以为同一 Job ID 重新插入 ledger 并更新 Health。该语义同时覆盖 catalog `source_fetch` 和一个 `user_feed_refresh` 影响多个订阅的路径。
- 权限失败、非 retryable 状态、返回另一 active Job、无 Health/ledger 均不产生误清理；`commit=False` 的 Job、ledger、Health-link 修改全部留在 caller-owned transaction 中并可一起回滚；两个连接并发 retry 只有一个成功。
- diagnostics 删除同 ID retry 的 ledger/更新时间/status 代际猜测，只使用 active Job 与显式 Health FK 的 detach/link provenance。新 outcome 恢复链接后 Health 为 `current`；尚未写新 outcome 的旧 Health 为 `historical`。

## TDD 证据

- 主回归先用两次真实 `run_worker_once()` 证明 RED：首轮 catalog `source_fetch` 为 `partial`，写入 `healthy + last_fetched_count=0 + application ledger`；同 ID retry 后第二轮 Job 已 `succeeded + fetched_count=3`，但 Health 仍为 0。
- 扩展 RED 批次共 9 个实例：6 个精确失败于 ledger/FK 未重开，3 个既有安全边界通过；覆盖 retry 后 `succeeded/failed/partial`、多订阅 full refresh、外事务回滚、权限/状态拒绝、active Job 复用、空 Health/ledger 与并发。
- 最小生产修改后专项 9/9 GREEN；真实 success 最终为 `healthy/current/unknown` 且 Health/Job result 均为 3，真实 failed/partial 最终 status、cause、Health role、Job result 与 `last_fetched_count` 一致。

## 验证

- diagnostics/job queue/source health/worker focused：260 项通过。
- API/MCP/schedule/reliability/Source Health Worker 邻接 11 文件：228 项通过；仅既有依赖 deprecation warnings。
- `.venv/bin/python -m py_compile ...`、`python3 -m json.tool project-defaults.yaml`、`python3 -m json.tool tests/test_impact_map.json`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 76.053 秒。

## 文件与范围

- `src/services/job_queue.py`
- `src/mcp/remote_diagnostics.py`
- `tests/test_job_queue.py`
- `tests/test_job_queue_reliability.py`
- `tests/test_remote_mcp_diagnostics.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-7-fix-r4-report.md`
- `WORKLOG.md`

Task 8+ 的 MCP 注册/server wiring、UI、OpenClaw Skill、生产开关与 canary 均未实现。
