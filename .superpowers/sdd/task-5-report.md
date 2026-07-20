# Task 5 Implementation Report

状态：DONE

基线：`743578a`

## 实现范围

- 新增 `DelegatedActor`、稳定 `AgentProposalError` 与 prepare-only `AgentChangeProposalService`。
- prepare 固定执行动态写开关 → 请求 write scope → live delegation/user/role → planner/object validation；facade 在 planner 前复核，proposal persistence 前再次复核。
- 新增 live delegation principal 读取，不依赖可伪造的 actor workspace/user/role/scopes，也不触碰 `last_used_at`。
- proposal 仅保存完整 v2 `plan.to_snapshot()`、安全重复列和 SHA-256 confirmation hash；store 权威 UTC 创建/到期时间作为返回值，严格 10 分钟。
- proposal 创建由外层事务包裹；snapshot、重复列、schema 或 sanitizer 失败全部回滚，pending limit 映射为 `proposal_limit`。
- 新增安全 guide/discovery/三类 prepare facade；发现只返回 enabled 的 public/workspace/本人 private，secret checker 仅接触最终可见行，输出不含 config、owner 或 secret env 名称。
- source type 过滤复用 Task 1 registry 的 public-Agent→catalog 映射；managed Apify 只能订阅已有可见来源。
- 未实现 apply、MCP 工具注册、remote models、server wiring 或 UI。

## TDD 证据

- RED：`./.venv/bin/pytest tests/test_remote_mcp_subscription_service.py -q` 在收集阶段按预期失败，原因是 `src.mcp.remote_subscription_service` 尚不存在。
- GREEN：新增 15 项 Task 5 回归全部通过，覆盖发现隔离、secret 安全、public type 映射、current-user unsubscribe、guard 顺序、actor 防伪、live role/revocation、v2/hash/TTL、动态 flag、limit/sanitizer、not_found/delete disposition 与 managed Apify。

## 验证

- `./.venv/bin/pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py -q`：252 项通过。
- `./.venv/bin/python -m py_compile src/services/agent_change_proposal.py src/mcp/remote_subscription_service.py src/services/source_type_registry.py src/storage/service_store.py`：通过。
- `./.venv/bin/python scripts/test_gate.py run --mode full`：22/22 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`。
- `git diff --check`：通过。

## 文件

- `src/services/agent_change_proposal.py`
- `src/mcp/remote_subscription_service.py`
- `src/services/source_type_registry.py`
- `src/storage/service_store.py`
- `tests/test_remote_mcp_subscription_service.py`
- `.superpowers/sdd/task-5-report.md`
- `WORKLOG.md`
