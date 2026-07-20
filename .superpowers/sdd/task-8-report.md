# Task 8 Implementation Report

状态：DONE

基线：`8d6f6a4`

## 实现范围

- 新增 strict/extra-forbid MCP 输入模型；`source.mode` 使用 `existing|private` 判别联合，Agent source type 复用 Task 1 当前 public registry 类型，所有工具外层参数同样拒绝 extra 且 validation error 不回显原始 input。
- `source.config` 是唯一开放的来源配置容器，仍由 Task 1 normalization 与共享 mutation planner 做最终校验；真实 client 覆盖 secret、Header、path、SQL 和伪造 identity 拒绝及脱敏。
- Remote MCP 按固定顺序暴露 14 个工具；10 个读取/引导/诊断工具、3 个 prepare 工具和 1 个 apply 工具使用精确独立 annotations。
- 全局 MCP auth 仍只要求 `inteliscope:read`；`DelegatedActor` 只由 verifier 产生的 claims 与 `AccessToken.scopes` 构造，写 flag/scope/live role/actor binding 继续由 proposal service 逐工具重验。
- `create_app()` 把同一 `SubscriptionMutationService`、`RuntimeStatusService` 与 SecretStore status callback 直接注入每 app 独立的 FastMCP；未使用内部 HTTP，也未共享 session manager。
- `RemoteMCPNotFound`、`AgentProposalError`、`SubscriptionMutationError` 映射稳定 code；未预期异常只返回 `internal_error request_id=mcp_...`。
- 审计日志固定为 delegation/tool/proposal/action/outcome/elapsed/request_id 七字段；缺失 proposal/action 使用 `-`，不记录 kwargs、异常文本、确认短语、source config 或 job 内容。
- 未修改 UI、OpenClaw Skill、Nginx、部署开关默认值或控制面合同。

## TDD 证据

- 初始 RED：`.venv/bin/pytest tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py -q` 得到 7 failed / 15 passed；精确缺口为 list 仍只有 6 工具，八个新增工具均返回 `Unknown tool`。
- 首轮 GREEN：同命令 22/22 通过；最终增加 generic `ValueError` internal masking 后为 23/23 通过。
- 真实 MCP Client 覆盖 14-tool 顺序/schema/annotations、原六读取与四个新增只读工具成功调用、prepare 不写业务表、exact apply、single-use consumed、read scope、flag off、跨用户隔离、输入边界和固定脱敏日志。

## 验证

- `.venv/bin/pytest tests/test_remote_mcp_http.py tests/test_remote_mcp_subscription_http.py tests/test_remote_mcp_diagnostics.py tests/test_nginx_remote_mcp.py -q`：219 项通过。
- Task 1/4–7 邻接（delegation/config/guide/proposal/mutation/read/source-health/job-queue）：666 项通过。
- `.venv/bin/python -m py_compile src/mcp/remote_models.py src/mcp/remote_server.py src/api/server.py`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 79.368 秒。

## 文件

- `src/mcp/remote_models.py`
- `src/mcp/remote_server.py`
- `src/api/server.py`
- `tests/test_remote_mcp_http.py`
- `tests/test_remote_mcp_subscription_http.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-8-report.md`
- `WORKLOG.md`

## 非目标

- Task 9+ 的 UI、Skill、控制面文档、impact map、发布启用、外部 OpenClaw canary 均未实现。
