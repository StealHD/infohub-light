# Task 7 Implementation Report

状态：DONE

基线：`a13506d`

## 实现范围

- 新增 `RemoteMCPDiagnostics.diagnose_source()` / `diagnose_job()`，使用同一固定响应 shape、固定原因分类和本地化建议文案。
- 按 source disabled → subscription disabled → schedule blocked → Worker unavailable → safe code → sanitized message → zero items → unknown 的顺序确定原因；code 匹配大小写不敏感，message 命中只给 `likely`。
- 来源诊断组合 owned subscription/source、真实 schedule、Source Health、validated related job、anonymous Worker status 与 `secret_configured: bool`；跨用户与不存在统一 `RemoteMCPNotFound("not_found")`。
- 任务诊断只读取 owned raw job；cause 使用固定安全说明，evidence 只保留有界时间、计数、safe code、allowlisted/typed result summary 和匿名 Worker 状态。
- 进一步拒绝 URL/query/Bearer、credential-shaped code/name/result identifier；不返回 payload/raw result、worker/claim/lock、config、secret env/value 或 user/workspace/owner identity。
- `remote_service.safe_job_result_summary()` 复用原有 result allowlist；普通 `list_jobs/get_job` 的字段、error 及 result projection 精确不变。
- 未注册 MCP 工具，未修改 server/API wiring、UI 或 OpenClaw Skill。

## TDD 证据

- 初始 RED：指定两文件命令在 collection 阶段出现 1 个预期错误，精确原因为 `ModuleNotFoundError: src.mcp.remote_diagnostics`（exit 2）。
- 首轮 GREEN：23 项中 22 项通过；唯一失败用例同时包含 timeout 与 Authorization/Bearer，按固定规则 auth 本应优先，收窄测试输入后 23/23 通过。
- 安全自审再 RED：safe-but-unmapped code 的 `cause.code` 丢失专项按预期 1 项失败；最小修正后保留安全 code 而分类仍为 unknown。
- 扩展覆盖包括五类 code/message 映射、全部 precedence、unknown、unsafe code、missing/stale Worker、zero items、cross-user/missing、related-job 污染、strict sanitization、read-only 与普通 job projection leak regression。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_diagnostics.py tests/test_remote_mcp_read_service.py tests/test_source_health.py tests/test_job_queue.py -q`：75 项通过。
- `.venv/bin/python -m pytest tests/test_source_schedule.py tests/test_job_queue_reliability.py tests/test_source_health_api.py tests/test_remote_mcp_config.py tests/test_remote_mcp_http.py -q`：70 项通过；仅有既存依赖 deprecation warnings。
- `.venv/bin/python -m py_compile ...`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`，耗时 67.841 秒。

## 文件

- `src/mcp/remote_diagnostics.py`
- `src/mcp/remote_service.py`
- `tests/test_remote_mcp_diagnostics.py`
- `tests/test_remote_mcp_read_service.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `WORKLOG.md`

## 非目标

- Task 8+ 的 14-tool MCP 注册、server/API injection、UI、Skill、生产启用与 canary 均未实现。
