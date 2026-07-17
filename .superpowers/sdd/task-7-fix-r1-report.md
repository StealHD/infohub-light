# Task 7 Fix R1 Report

状态：DONE

基线：`744a6cd`

## 审查项修复

- Important #1：来源诊断现在完整收集并逐一验证 Health/Schedule 显式 Job 外键；active Schedule Job 优先，否则按 `(created_at, id)` 确定性取最新，只有没有合法显式候选时才执行直接 source/subscription 回退。owned `user_feed_refresh` 可通过真实 Health/Schedule 外键成为关联证据，即使 Job 自身没有 source/subscription 字段。
- Important #2：Job 的 `no_items` 只使用目标 Job 自身，要求 `status=succeeded` 且 allowlisted `fetched_count` 明确为 0；不再借用旧 Source Health，也不再用 `item_count=0` 替代。Source 仅使用当前 healthy 最后成功尝试或 validated related succeeded Job。
- Important #3：所有外部 code、result identifier 与 target display name 同时经过 credential value/URL 与独立 sensitive key-label 分类；`*_SECRET_ENV`、`*_TOKEN_ENV`、`*_API_KEY` 在 Job/Health code、`snapshot_id/run_status` 和名称路径均零泄漏。
- Minor #4：`diagnose_source()` / `diagnose_job()` 各自在入口只取一次 `checked_at`，并将同一时刻传给 runtime freshness、schedule precedence 与 evidence。

## TDD 证据

- RED：新增反例后，`tests/test_remote_mcp_diagnostics.py -q` 共 18 项按预期失败：related Job 2 项、`no_items` 2 项、credential label/name 12 项、递增 clock 2 项；其余用例通过。
- GREEN：最小修改仅位于 diagnostics 关联选择、分类、标量过滤与时间传递；同一诊断文件 45 项全部通过。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py tests/test_source_health.py tests/test_job_queue.py -q`：94 项通过。
- `.venv/bin/python -m pytest tests/test_source_schedule.py tests/test_job_queue_reliability.py tests/test_source_health_api.py tests/test_remote_mcp_config.py tests/test_remote_mcp_http.py -q`：70 项通过；仅既存依赖 deprecation warnings。
- `.venv/bin/python -m py_compile src/mcp/remote_diagnostics.py tests/test_remote_mcp_diagnostics.py`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 70.226 秒。

## 文件与范围

- `src/mcp/remote_diagnostics.py`
- `tests/test_remote_mcp_diagnostics.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-7-fix-r1-report.md`
- `WORKLOG.md`

普通 `list_jobs/get_job` 投影保持不变；未注册 MCP 工具，未修改 server/API wiring、UI、Skill、生产开关或任何业务写路径。
