# Task 6 Implementation Report

状态：DONE

基线：`13f5637`

## 实现范围

- 新增 `apply_subscription_change()` facade 与 `AgentChangeProposalService.apply()`，未注册 MCP 工具、未改 UI/server wiring。
- apply 拒绝调用方已有事务；preflight 后自行 `BEGIN IMMEDIATE`，事务内再次执行动态 flag → request write scope → live delegation/user/role/canonical scopes，并使用 fresh actor 调 Task 3 mutation service。
- proposal ID 不存在或跨 workspace/user/delegation 统一 `not_found`；只接受 pending，applied 映射 `proposal_consumed`，expired 映射 `proposal_expired`。
- confirmation 仅做 SHA-256 后以 `hmac.compare_digest()` 精确比较；明文不持久化、不进入结果或日志。
- 到期判断绑定 store 权威 UTC clock；`now >= expires_at` 只提交 expired 状态。若时间在 mutation 与 proposal transition 之间跨界，先回滚全部业务写，再单独原子提交 expired。
- 同一事务核对 v2 snapshot 与 kind/targets/preview/fingerprints 重复列，restore sealed plan，执行 `apply_plan(commit=False, post_commit_cleanup=collector)`，最后写 applied 与固定 allowlist summary。
- `_safe_result()` 仅返回 action、source/subscription ID、enabled 状态及 schedule interval；不返回 raw config、workspace/user/owner、secret、source key、内部 marker 或文件路径，返回结果与 stored summary 完全一致。
- 成功 commit 后才 `cleanup.run()`；confirmation/stale/权限/expiry/quota/conflict/mutation/store 失败均 rollback/discard，proposal 除 expiry 外保持 pending。
- 双连接并发由同一 `BEGIN IMMEDIATE` 串行化，恰好一个 applied、另一个 consumed，业务表只写一次。

## TDD 证据

- RED：Task6 两文件命令出现 17 个预期失败，均因 `RemoteMCPSubscriptionService.apply_subscription_change` 不存在；store clock 专项按预期暴露 caller 时间可提前 expire。
- GREEN：43 项 Remote subscription facade、104 项 proposal store、133 项 mutation（合计 280）通过；覆盖 exact phrase、single-use、隔离、10 分钟边界/time crossing、动态授权、duplicate/fingerprint stale、quota/source-key、summary/store 异常回滚、cleanup 与并发。

## 验证

- `.venv/bin/python -m pytest tests/test_remote_mcp_subscription_service.py tests/test_agent_change_proposals.py tests/test_subscription_mutation_service.py -q`：280 项通过。
- `.venv/bin/python -m pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py tests/test_media_cache_unit.py -q`：36 项通过。
- `.venv/bin/python -m py_compile ...`、`python3 -m json.tool project-defaults.yaml`、`git diff --check`：通过。
- `.venv/bin/python scripts/test_gate.py run --mode full`：最终 fresh gate 22/22 通过，`first_failure=null`、`mapping_miss=false`、耗时 76.189 秒。

## 文件

- `src/services/agent_change_proposal.py`
- `src/mcp/remote_subscription_service.py`
- `src/storage/service_store.py`
- `tests/test_remote_mcp_subscription_service.py`
- `tests/test_agent_change_proposals.py`
- `docs/superpowers/plans/2026-07-17-openclaw-subscription-management-diagnostics.md`
- `WORKLOG.md`

## 非目标

- 未实现 Task 7+、MCP tool registration/models/server wiring、UI、OpenClaw Skill 或生产启用。
