# Task 5 Fix R2 Report

状态：DONE

基线：`da66d05`

## 修复范围

- Agent-safe `plan_create()` 对 existing source 从 workspace/owner accessible 提升为 enabled/visible 权威校验；disabled source 无论是否已有 subscription 均稳定返回 `not_found`。
- `_revalidate_live_plan()` 对 existing create 使用同一 visible 规则。facade 预检后、planner 读取前禁用会拒绝且不写 proposal；planner 完成后再禁用，Task 3 `apply_plan()` 返回 `not_found` 且不创建或更新 subscription。
- 保持 REST 专用 `rest_create_subscription()`、`rest_update_subscription()`、`rest_upsert_source()` 等既有权限与生命周期语义；未新增 Agent allow-disabled 入口。
- registry 新增无 guide 投影副作用的 `validate_agent_source_type()`，精确拥有 `rss/telegram/github/reddit/twitter/website/youtube/apify` 八项 public enum；guide 与 matcher 共用该 validator。
- `list_available_sources()` 在读取目录行前独立验证 filter，因此空目录与非空目录的未知类型都稳定返回 `unsupported source type`。
- 移除 Task 3 测试中 disabled existing source 经 Agent create/upsert 的无生产理由合同；quota final-inactive 继续由 existing subscription update 与同 plan source-disable 场景覆盖。
- 未实现 Task 6 apply orchestration、MCP 工具注册、server wiring、UI 或其他 Task 6+ 能力。

## TDD 证据

- RED：空目录 unknown public type 未抛错；facade 预检与 planner 之间禁用仍生成 proposal；disabled existing source 的 new/existing subscription 两态仍可 plan；planner 后禁用在 apply 返回 `invalid_plan_snapshot` 而非权威 `not_found`；registry public validator 尚不存在，共 6 个预期失败。
- GREEN：最小修改为 registry validator 及 existing-create planner/apply 两个 `_visible()` 校验点；专项 9 项通过。

## 验证

- `./.venv/bin/pytest -o addopts='' -q --disable-warnings tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py tests/test_api_service.py tests/test_api_permissions_matrix.py tests/test_source_schedule.py tests/test_source_health.py tests/test_source_type_registry.py tests/test_agent_delegations.py tests/test_agent_delegation_api.py`：433 passed。
- `./.venv/bin/pytest -o addopts='' -q --disable-warnings tests/test_source_setup_guidance.py tests/test_remote_mcp_http.py tests/test_remote_mcp_config.py tests/test_remote_mcp_read_service.py tests/test_nginx_remote_mcp.py`：308 passed。
- Python compile：通过。
- `./.venv/bin/python scripts/test_gate.py run --mode full`：22/22 通过，`first_failure=null`、`mapping_miss=false`、`ui_impacted=false`。
- 默认配置 JSON 与最终 diff 检查：通过。

## 文件

- `src/services/subscription_mutation.py`
- `src/services/source_type_registry.py`
- `src/mcp/remote_subscription_service.py`
- `tests/test_subscription_mutation_service.py`
- `tests/test_source_type_registry.py`
- `tests/test_remote_mcp_subscription_service.py`
- `.superpowers/sdd/task-5-fix-r2-report.md`
- `WORKLOG.md`
