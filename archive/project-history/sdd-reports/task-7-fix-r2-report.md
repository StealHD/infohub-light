# Task 7 Fix R2 Report

状态：DONE

基线：`0aab473`

## 第二轮审查项修复

- Important #1：`diagnose_job()` 使用目标 Job 自身作为完整归因边界；source 只提供经过完整标量过滤的显示名，Schedule 与 Source Health 不再参与 Job cause/status。匿名 Worker readiness 只对目标 Job 的 `queued/running` 状态生效，terminal Job 始终使用自身 code/message/result/status。
- Important #2：来源关联 Job 保留 `health/schedule/health_and_schedule/fallback` provenance。若 Schedule 选中的更新 Job 已 `failed` 且不是 `health.last_job_id`，cause/status 只由该 Job 决定，旧 Health 继续保留但明确标记为 `historical` evidence；同一次 Health Job 仍维持现有 precedence。
- Important #3：诊断 result count 只接受原始 JSON 非负整数并排除 `bool`；`-1`、`0.5`、`"0"` 均从 evidence 省略且不能触发 `no_items`，整数 `0` 的 Job/Source 正向路径保持不变。
- Important #4：新增 diagnostics-local 完整标量 credential-label classifier，复用有界 NFKC/percent-decode copies，同时严格覆盖 `AWS_ACCESS_KEY_ID`、`SSH_PRIVATE_KEY`、`*_KEY_ENV`、`*_API_KEY_ENV` 及既有 secret/token/api-key 形态。该分类应用于 Job/Health/Schedule code、`snapshot_id/run_status` 和 Source/Job target name；名称先检查完整标量再截断。通用 mapping-key classifier 未修改。

## TDD 证据

- 首轮 RED：新增 Job 归因、Source provenance/新 terminal Job、Job/Source 畸形 count 与 credential-label 全出口反例后，`tests/test_remote_mcp_diagnostics.py -q` 出现 34 个预期失败，其余既有用例通过。
- 安全自审 RED：补充“敏感 name 位于 120 字符截断边界之后”专项，确认 1 个预期失败；完整标量分类后转 GREEN。
- GREEN：diagnostics 90 项全部通过；两个布尔值均被排除，整数 0 的 Job/Source `no_items` 正向用例继续通过。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py tests/test_source_health.py tests/test_job_queue.py -q`：139 项通过。
- `.venv/bin/python -m pytest tests/test_source_schedule.py tests/test_job_queue_reliability.py tests/test_source_health_api.py tests/test_remote_mcp_config.py tests/test_remote_mcp_http.py -q`：70 项通过；仅既存依赖 deprecation warnings。
- `.venv/bin/python -m py_compile src/mcp/remote_diagnostics.py tests/test_remote_mcp_diagnostics.py`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`。

## 文件与范围

- `src/mcp/remote_diagnostics.py`
- `tests/test_remote_mcp_diagnostics.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-7-fix-r2-report.md`
- `WORKLOG.md`

普通 `list_jobs/get_job` 与 `safe_job_result_summary()` 未修改；诊断保持只读，未注册 MCP 工具，未修改 server/API wiring、UI、Skill、生产开关或业务写路径。
