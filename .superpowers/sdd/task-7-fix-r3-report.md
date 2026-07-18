# Task 7 Fix R3 Report

状态：DONE

基线：`2f36cf1`

## 第三轮审查项修复

- Important #1：来源诊断将选中的 `queued/running` Job 视为当前尝试，返回其精确 status，并把旧 Health 标为 `historical`。同 ID 手工 retry 通过真实 `user_source_health_applications` ledger 与 `job.updated_at > health.updated_at` 识别代际；新成功尝试在与旧失败 Health 冲突时胜出，新失败尝试即使 error code 未变化也由 Job 决定 `status/cause`，不会继续返回旧 `degraded/failing` Health。
- Important #2：Job/Health/Schedule code、`snapshot_id/run_status` 与截断前完整 target name 共用 diagnostics-local fail-closed 标量分类。它拒绝紧凑 `Bearer/Basic` 值、terminal `*_KEY`、`*_CONNECTION_STRING`、`credential(s)` 与既有 secret/token/key-env 形态，同时保留 `StorageKeyRotation`、`ConnectionStringTheory`、`Basic Engineering News`、`Bearer Market Report` 等普通业务标量。
- 普通 `list_jobs/get_job` 投影、通用 mapping-key classifier 与业务写路径保持不变；诊断继续只读，未注册新 MCP 工具。

## TDD 与独立复核证据

- 接管前 R3 修复已记录 active/retry 4 个反例与完整标量 42 个反例的 RED→GREEN；接管后重新逐行核对生产 `JobQueue.retry_job()`、Worker finalize 顺序与 Source Health ledger，而非直接采用既有通过结论。
- 新增同 ID retry 再次以相同 `TimeoutError` 失败的反例，先按预期 RED：诊断返回 `status=degraded` 而非 `failed`；收窄到 ledger-aware attempt provenance 后 GREEN。
- 新增 `Basic Engineering News` / `Bearer Market Report` source/job name 反例，先出现 4 个预期 RED；将授权值拒绝收窄为紧凑标点分隔形态后 GREEN，既有紧凑 Bearer/Basic 全出口拒绝用例继续通过。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_diagnostics.py -q`：191 项通过。
- `.venv/bin/python -m pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py tests/test_source_health.py tests/test_job_queue.py -q`：240 项通过。
- schedule/job retry/health Worker/API/MCP 邻接 10 文件：143 项通过；仅既有依赖 deprecation warnings。
- `.venv/bin/python -m py_compile src/mcp/remote_diagnostics.py tests/test_remote_mcp_diagnostics.py`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 81.82 秒。

## 文件与范围

- `src/mcp/remote_diagnostics.py`
- `tests/test_remote_mcp_diagnostics.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-7-fix-r3-report.md`
- `WORKLOG.md`

Task 8+ 的 MCP 注册/server wiring、UI、OpenClaw Skill、生产开关与 canary 均未实现。
