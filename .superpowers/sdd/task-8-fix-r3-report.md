# Task 8 Fix R3 Report

状态：DONE

基线：`416a5c3`

## 根因与修复

- `mcp==1.28.1` 的 `FuncMetadata.pre_parse_json()` 对非字符串字段的字符串输入执行 `json.loads()`，但 SDK 只在内部忽略 `JSONDecodeError`。超过 Python integer-string 限制的数字字符串会抛 `ValueError`，12 万层嵌套 JSON 数组字符串会抛 `RecursionError`。
- 两类异常均发生在 claim-derived delegation limiter 已消耗一个 token 之后、Pydantic validation 之前；原适配器只捕获 `ValidationError`，因此 SDK/Python 异常文本被直接返回，且没有固定审计记录。
- `SafeRemoteMCP.call_tool()` 仅将现有捕获元组收窄扩展为 `(ValidationError, ValueError, RecursionError)`，统一返回 `invalid_request` 并写入一条固定七字段日志。未捕获 `Exception`/`BaseException`，`TypeError`、`SystemExit`、`MemoryError` 等仍不会被这个输入拒绝分支吞掉。
- auth、registered-tool lookup、limiter 位置、同一 `pre_parse_json()` 与 argument model 均未移动；成功预解析仍委托 `super().call_tool()`，不改变 SDK schema/coercion 语义。

## TDD 证据

- RED：两个真实 `ClientSession` 用例为 2 failed / 0 passed。`ValueError` 响应泄漏 `Exceeds the limit ... 4301 digits`，`RecursionError` 响应泄漏 `Stack overflow ... decoding a JSON array`；两次都已计费但没有 `remote_mcp_call` 日志。
- GREEN：相同两个用例 2 passed / 0 failed。每个场景都由目标异常调用 + 9 次成功调用 + 第 11 次精确 `rate_limited` 证明目标调用恰好计费一次；目标响应精确为 `invalid_request`，恰好一条七字段日志，输入、异常类型与异常文本零回显。

## 验证

- Task 8 focused/transport/diagnostics/Nginx 四文件：230 项通过。
- Task 1/4–7 更宽邻接 11 文件：854 项通过；覆盖 guide、delegation、config、proposal、mutation、read、diagnostics、source-health 和 job-queue。
- `.venv/bin/python scripts/test_gate.py run --mode full`：22/22 commands 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`，耗时 81.778 秒；结果为 `.test-results/20260718T071147Z-86453/result.json`。
- Python compile、`project-defaults.yaml` JSON、`tests/test_impact_map.json` JSON 与 `git diff --check`：通过。

## 文件与范围

- `src/mcp/remote_server.py`
- `tests/test_remote_mcp_subscription_http.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `.superpowers/sdd/task-8-fix-r3-report.md`
- `WORKLOG.md`

未修改 UI、API/架构控制合同、Task 9+、生产开关或真实 OpenClaw canary。
