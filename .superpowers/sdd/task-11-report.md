# Task 11 Report: Control Contracts, Impact Mapping, and Final Acceptance

状态：DONE（本地合同与映射）；发布验证未执行。

基线：`a482996`

## 完成内容

- `API_CONTRACT.md` 规定 read/write delegation access、scopes 和两个 feature flag；覆盖精确 14 个 MCP tools、严格身份无关输入边界、annotation、proposal lifecycle、诊断 shape、投影限制与稳定错误。
- `ARCHITECTURE_CONTRACT.md` 指定 REST/MCP 共用 `SubscriptionMutationService`，并分配 proposal 和 diagnostics owner；Remote MCP 维持 stateless，直接访问 Service/Store，禁止内部 HTTP loop。
- `UI_CONTRACT.md` 规定 read/write creation choice、viewer 限制、capability chip，以及按 connection access 生成精确 6/14 toolFilter；不会保存 token 或执行本地 Gateway/OpenClaw probe。
- `DECISION_LOG.md` 新增 D025：server-enforced prepare/apply、opt-in write delegation、OpenClaw Elicitation 现有限制与 Web-only secret boundary。
- `PLAN.md` 将 subscription management 本地实现与 staging/canary 分离；从非目标中移除受确认的私有 subscription/source mutation，保留 MCP 不开放的密钥、共享来源、任务和 Feed 状态写入。
- `tests/test_impact_map.json` 将 proposal/mutation、Remote MCP subscription/diagnostics/Skill 测试和既有 React UI 路由纳入 API/store/Remote MCP focused selection。

## 验证

`python` 在该 worktree 不存在；唯一一次等价 `python3 scripts/test_gate.py plan --json` 因缺少 snapshot 或 Git `--base/--head` 输入返回配置错误，未生成选择计划。`project-defaults.yaml` 与 `tests/test_impact_map.json` JSON lint、`git diff --check` 均通过。未运行 pytest、npm、build、performance benchmark、full gate 或 real OpenClaw canary。

## 发布边界

真实 OpenClaw canary 与 100-call performance acceptance 未执行。发布仍需数据库 backup、API-only staging（subscription writes flag off）、schema/integrity/foreign-key 检查、TLS `/mcp` Authorization forwarding 与 Nginx limits、one read/write canary、revoke 后 401、两用户隔离，再经明确授权开启写 flag。回滚仅关闭 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`；保留 additive schema v7 和 read-only MCP。
