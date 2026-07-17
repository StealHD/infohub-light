# Task 5 Fix Report

状态：DONE

基线：`49cacb6`

## 修复范围

- proposal persistence 在确认当前连接无事务后执行 `BEGIN IMMEDIATE`，并在事务内按动态 write flag → 请求 write scope → live delegation/user/role/canonical scopes 顺序重建 fresh actor；随后才生成 snapshot、安全重复列、执行 sanitizer 和 insert，所有异常统一回滚。
- proposal store 在同一写事务内纵深检查 delegation 未撤销/未过期、用户 enabled 且 workspace 绑定一致、live role 可写、canonical live scopes 含 write；稳定授权失败不再映射为 `invalid_plan_snapshot`。
- discovery 改为显式 public matcher：GitHub release/user、Reddit subreddit/user、Telegram、canonical YouTube RSS、Twitter managed X/profile 与其余 generic Apify 分离；RSS/Website 明确共享同一非 YouTube RSS 集合，Hacker News 不属于八个 public filters。
- discovery 对结果 ID 去重并按 scope/name/id 稳定排序；secret checker 仍只接触最终可见、已过滤、未订阅排除后的行，callback 异常改为固定 503 `source_discovery_unavailable`，不保留原异常 context 或 `secret_env`。
- 未实现 Task 6 apply、MCP 工具注册、server wiring 或 UI。

## TDD 证据

- RED：Task 5 facade 首轮出现 6 个预期失败，分别命中 discovery matrix、secret checker 泄露与 revoke/disable/role/scopes 四种竞态；proposal store 四种 inactive-principal 纵深测试全部按预期失败。
- RED/GREEN mutation check：临时移除事务内最终 guard 后，动态 flag 专用回归按预期 `DID NOT RAISE`；恢复 guard 后该回归通过。
- GREEN：Task 5/邻接 delegation、remote HTTP、registry/guidance、deployment focused 共 594 项通过。

## 验证

- `./.venv/bin/pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_remote_mcp_http.py tests/test_source_type_registry.py tests/test_source_setup_guidance.py tests/test_prepare_service_deployment.py -q`：通过（594 项）。
- `./.venv/bin/pytest tests/test_maintenance.py tests/test_prepare_service_deployment.py -q`：通过（6 项）。
- `./.venv/bin/python scripts/test_gate.py run --mode full`：22/22 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`。
- `git diff --check`：通过。

## 文件

- `src/services/agent_change_proposal.py`
- `src/storage/service_store.py`
- `src/services/source_type_registry.py`
- `src/mcp/remote_subscription_service.py`
- `tests/test_remote_mcp_subscription_service.py`
- `tests/test_agent_change_proposals.py`
- `tests/test_maintenance.py`
- `tests/test_prepare_service_deployment.py`
- `.superpowers/sdd/task-5-fix-report.md`
- `WORKLOG.md`
