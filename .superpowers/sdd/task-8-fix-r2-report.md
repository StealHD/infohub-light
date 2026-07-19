# Task 8 Fix R2 Report

状态：DONE

基线：`548c5f5`

## 根因与修复

- 本机 `mcp==1.28.1` 的 Streamable HTTP 路径先执行 bearer authentication、auth context 和 required read scope，再进入 `FastMCP.call_tool()`。已注册工具随后由 app-local `SafeRemoteMCP.call_tool()` 预检参数；原 delegation limiter 只在预检之后的 `run_tool()`，所以 Pydantic validation 拒绝不会消费 bucket。
- `DelegationRateLimiter` 新增单调 `clock` 注入缝，并仍固定为每 delegation `60/minute, burst 10`。每个 `create_remote_mcp()` 创建自己的 limiter，并注入同一个 app 的 `SafeRemoteMCP`。
- `SafeRemoteMCP.call_tool()` 只对已注册且具有 claim-derived delegation ID 的调用，在参数预检前消费一次 token。限流拒绝只返回稳定 `rate_limited`，并恰好记录一条固定七字段日志；validation 仍只返回 `invalid_request` 并记录一次。两条拒绝路径均不读取、序列化或记录 arguments、异常、ValidationError 或敏感值。
- `run_tool()` 不再判定 limiter，继续独占正常结果与业务错误的单条审计。因此 validation、正常结果、`not_found` 等业务错误均各消费一次，正常调用不会双计或双日志。
- 未认证请求由 SDK auth middleware 在工具边界前拒绝，不审计、不计费；unknown tool 仍走 SDK 原路径并返回 `Unknown tool: <name>`，不审计、不计费。14 工具顺序、typed schema、annotations、claim actor、transport 和 app/session isolation 未改变。

## TDD 证据

- RED：5 个新增 selector 为 5 failed / 0 passed。limiter 不接受 `clock`；同 delegation 的第 11 次 invalid 调用仍返回 `invalid_request`；混合调用、双 app 和 unauthenticated/unknown 边界均证明 validation 没有进入 bucket。
- GREEN：相同 5 个 selector 为 5 passed / 0 failed。真实 `ClientSession` 验证十次 invalid 后第 11 次精确 `rate_limited`；invalid、正常成功和稳定 `not_found` 业务错误共享 bucket 且各计一次；同一 delegation 在两个 app 中隔离；每个已注册调用恰好一条七字段日志且零输入/异常/敏感值泄漏。
- 注入时钟单测验证 burst 10、60/minute 即每秒补充一个 token，以及补充不超过 burst。

## 验证

- Task 8 focused/transport/diagnostics/Nginx 四文件：228 项通过。
- Task 1/4–7 更宽邻接 11 文件：854 项通过；覆盖 delegation、config、guide、proposal、mutation、read、diagnostics、source-health 和 job-queue。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 77.365 秒。
- `.venv/bin/python -m py_compile ...`、`python3 -m json.tool project-defaults.yaml`、`python3 -m json.tool tests/test_impact_map.json` 与 `git diff --check`：通过。

## 文件与范围

- `src/mcp/remote_server.py`
- `tests/test_remote_mcp_http.py`
- `tests/test_remote_mcp_subscription_http.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-8-fix-r2-report.md`
- `WORKLOG.md`

未修改 UI、API/架构控制合同、Task 9+、生产开关或真实 OpenClaw canary。
