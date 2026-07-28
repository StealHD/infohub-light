# Task 8 Fix R1 Report

状态：DONE

基线：`3a64269`

## 审查项修复

- 已确认本地 `mcp==1.28.1` 的真实调用链为：已认证 Streamable HTTP 请求 → `FastMCP.call_tool()` → app 自有 `ToolManager.call_tool()` → `Tool.run()` → `FuncMetadata.call_fn_with_arg_validation()` → Pydantic argument model `model_validate()` → 注册的业务函数。原实现的 `run_tool()` 位于最后一步之后，因此无法映射或审计参数验证失败。
- 新增每 app 独立的 `SafeRemoteMCP`，只覆盖 SDK 最外层 `call_tool()` adapter。它使用工具现有 `FuncMetadata.pre_parse_json()` 与同一公开 argument model 在 `Tool.run()` 前预检；`ValidationError` 只返回固定 `invalid_request`，并恰好记录一次固定七字段 `remote_mcp_call`。
- 验证失败日志固定使用 `proposal_id=-`、`action=-`、`outcome=invalid_request` 和新的 `request_id=mcp_...`；拒绝分支不检查、序列化或记录 arguments、ValidationError、异常文本或输入值。验证成功继续调用 SDK 原路径，因此现有 `run_tool()` 仍是正常调用及业务错误的唯一审计点，不双日志。
- 保留所有公开 typed schema、`extra="forbid"`、`hide_input_in_errors=True`、14 工具顺序与 annotations；没有全局 monkeypatch、跨 app server/manager/session 共享或 UI 变更。

## TDD 证据

- RED：真实 `ClientSession.call_tool()` 参数化覆盖外层 extra、nested extra、错误 discriminator 与范围错误，4/4 按预期失败；响应分别暴露 SDK/Pydantic `extra_forbidden`、`union_tag_invalid`、`less_than_equal` 等明细，且缺少固定审计记录。
- GREEN：最小 adapter 后同一回归 4/4 通过；每个响应精确等于 `invalid_request`，每次精确一条七字段日志，submitted sensitive value 与 validation detail 在响应/日志均不可见。
- Task 8 两个 HTTP focused 文件 27 项通过；既有 internal-error exact-one 日志、prepare/apply audit、rate limit、schema/annotations 和 app/session isolation 回归继续通过。

## 验证

- `.venv/bin/pytest tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py tests/test_remote_mcp_diagnostics.py tests/test_nginx_remote_mcp.py -q`：223 项通过。
- Task 1/4–7 邻接 11 文件：666 项通过；覆盖 delegation/config/guide/proposal/mutation/read/source-health/job-queue。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 78.37 秒。
- `.venv/bin/python -m py_compile src/mcp/remote_models.py src/mcp/remote_server.py src/api/server.py`、两个 JSON 校验与 `git diff --check`：通过。

## 文件与范围

- `src/mcp/remote_server.py`
- `tests/test_remote_mcp_subscription_http.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-8-fix-r1-report.md`
- `WORKLOG.md`

Task 9+ UI/Skill、控制面合同、生产启用与真实 OpenClaw canary 仍不在本修复范围。
