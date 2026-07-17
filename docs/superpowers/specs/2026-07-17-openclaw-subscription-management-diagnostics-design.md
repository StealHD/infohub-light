# OpenClaw 订阅管理与可解释诊断设计

## 1. 目标

把现有只读 Remote MCP 扩展为受控的订阅管理入口，使本地 OpenClaw 可以：

1. 按来源类型逐项指导用户提供信息；
2. 订阅已有来源，或原子创建当前用户的私有来源并订阅；
3. 修改私有来源、订阅偏好和单来源计划；
4. 取消订阅，并按用户每次明确选择决定是否同时停用私有来源；
5. 基于持久化的安全诊断解释来源异常和任务失败；
6. 对可通过来源或订阅配置修复的问题生成变更预览，经确认后执行。

本阶段不允许 Agent 创建或修改团队/公共来源，不接受任何聊天内密钥，不新增刷新、重试、收藏、已读、任务取消、服务器侧 Agent 或模型服务。

## 2. 已确认原则

- `owner/admin/member` 可以通过有写权限的 delegation 管理自己的私有来源和订阅；`viewer` 保持只读。
- 所有写操作必须先生成完整预览，再由第二次 MCP 调用确认执行。
- 删除前每次都询问“仅取消订阅”或“同时停用私有来源”，不设置默认选项。
- Apify 等需要密钥的来源不在聊天中接收密钥；缺少可用来源时引导用户到 Web 配置。
- 诊断使用真实、脱敏、持久化证据；不能确定时明确返回未知，不允许模型虚构根因。
- 现有 delegation 永久保持只读；写权限只能通过 Web UI 显式创建的新连接获得。

## 3. 方案选择与 OpenClaw 兼容性

选择服务端两阶段提案，而不是 Skill 单独约束或强制 Web 审批。这样可以防止单次工具调用直接修改业务数据，并在执行时重新检查权限、配额、所有权和目标版本。

MCP Python SDK 支持 Elicitation，但本机 OpenClaw 2026.7.1 的通用 `mcp.servers` 客户端没有注册 Elicitation 处理器，普通请求会失败关闭。因此本阶段不能声称协议层证明了真人确认。兼容流程固定为：

1. prepare 工具返回短时提案、完整变更和唯一确认短语；
2. Skill 把预览展示给用户，并要求用户明确回复该短语；
3. apply 工具同时提交提案 ID 和确认短语；
4. 服务端校验后单次执行或拒绝。

该流程能阻止直接单步写入、过期提案、跨用户/跨连接使用和陈旧覆盖，但不能证明确认短语一定由真人输入。未来 OpenClaw 通用 MCP 支持 Elicitation 后，可以把第 2 步替换为原生确认，不改变业务提案模型。

## 4. Delegation 权限与管理 API

保留 `inteliscope:read`，新增 `inteliscope:subscriptions:write`。写 delegation 必须同时拥有两个 scope；MCP 全局认证仍要求 read scope，写工具再检查 write scope 和用户角色。

`POST /api/me/agent-delegations` 扩展为：

```json
{"name":"My Mac","access":"read|subscriptions_write"}
```

`access` 缺省为 `read`，保证旧客户端兼容。viewer 请求 `subscriptions_write` 返回 403。GET 列表返回每个连接的 `access/scopes`；现有记录不迁移 scope。助手连接页创建时明确展示“只读”和“可管理订阅”，说明后者仍不能管理密钥、共享来源或任务。一次性令牌和五连接/90 天规则不变。

新增 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false`。关闭时只读 MCP 正常工作，不能创建写连接，已有写连接的所有 prepare/apply 调用返回 `subscription_writes_disabled`。

## 5. MCP 工具合同

保留现有六个工具，新增以下八个工具。

### 5.1 引导与发现

`get_source_setup_guide(source_type=null, locale="zh-CN")`

- 不传类型时返回八类来源的名称、用途、自助创建状态和最少必填信息。
- 传类型时返回字段名、标签、必填、默认值、类型、范围、选项、接受格式、示例、获取方法、注意事项和密钥/Web 前置条件。
- `locale` 首版只允许 `zh-CN` 与 `en`；找不到翻译时回退 `en`，字段标识不翻译。

`list_available_sources(source_type=null, unsubscribed_only=false)`

- 返回调用者可见的公共、团队和自己的私有来源，以及是否已订阅。
- 只返回允许公开的来源身份摘要、默认频道/主题和 `secret_configured` 布尔值；不返回 `secret_env`、原始配置或其他用户身份。

### 5.2 两阶段写入

`prepare_create_subscription(source, subscription={}, schedule=null)`

- `source` 使用判别联合：`mode=existing + source_id`，或 `mode=private + type/display_name/config` 及可选描述、默认频道/主题。
- 私有来源和订阅在 apply 时同一事务创建；类型、scope 和 secret 引用不能由客户端任意指定。
- `subscription` 允许 `enabled/override_channel/override_topics/personal_tags/analysis_mode/priority`。
- `schedule` 只允许现有固定 interval 和 enabled；未提供时不额外创建启用计划。

`prepare_update_subscription(subscription_id, source_updates=null, subscription_updates=null, schedule_updates=null)`

- 至少提供一组更新。
- `source_updates` 仅适用于调用者拥有的私有来源，不能改类型、scope、owner 或 secret。
- 订阅与计划字段复用 REST 的现有校验、配额和启用条件。

`prepare_delete_subscription(subscription_id, source_disposition)`

- `source_disposition` 必填且只允许 `keep` 或 `disable_private`。
- `disable_private` 只适用于调用者拥有的私有来源；共享来源或非所有者请求返回 403。

`apply_subscription_change(proposal_id, confirmation_text)`

- 只接受同一 delegation、用户和 workspace 的 pending 提案。
- 提案有效 10 分钟、只能成功使用一次；确认短语必须完全匹配。
- apply 使用 `BEGIN IMMEDIATE`，重新检查 delegation scope、用户角色、功能开关、目标 `updated_at` 指纹、所有权、来源可见性、配额和 source key 冲突。
- 目标变化返回 `proposal_stale`，不得部分执行；用户必须重新 prepare。

prepare 工具会写提案记录，因此标记 `readOnly=false/destructive=false/idempotent=false/openWorld=false`；apply 标记 `readOnly=false/destructive=true/idempotent=false/openWorld=false`。引导、发现和诊断工具保持只读标记。

### 5.3 可解释诊断

`diagnose_source(subscription_id)`

- 组合订阅/来源启用状态、计划状态与 last skip reason、Source Health、最近一次关联 Job 和密钥是否已配置。
- 只允许当前用户的 subscription；跨用户与不存在统一 `not_found`。

`diagnose_job(job_id)`

- 组合安全 Job 摘要、脱敏错误、attempt/max attempts、时间、固定 result summary、关联来源名称和无身份的 Worker readiness。
- 不返回 payload、worker/claim/lock、原始 result、堆栈、URL query、Header、密钥或用户/workspace ID。

两个诊断工具返回统一结构：

```json
{
  "target": {"kind":"source|job","id":"...","name":"..."},
  "status": "failing",
  "cause": {
    "category": "network_timeout",
    "code": "upstream_timeout",
    "title": "上游连接超时",
    "message": "脱敏后的有界说明",
    "confidence": "confirmed|likely|unknown",
    "retryable": true
  },
  "evidence": [{"kind":"consecutive_failures","value":2}],
  "suggested_actions": [
    {"code":"check_source_target","mode":"prepare_change|web|wait|contact_admin","label":"检查来源目标"}
  ],
  "related_job_id": "job_example"
}
```

原因分类固定为 `auth_missing/rate_limited/network_timeout/upstream_rejected/invalid_source_config/source_disabled/subscription_disabled/schedule_blocked/worker_unavailable/no_items/unknown`。分类由确定性代码根据显式状态和错误码生成；只有在映射脱敏 message 时才能使用 `likely`。没有证据时返回 `unknown` 和“现有记录不足以确定原因”。

## 6. 逐来源指导

扩展 `source_type_registry` 作为 Web UI、REST 和 MCP 的唯一字段真源。每个类型增加双语说明、字段示例、接受格式、获取方法、自助创建状态和 Web 前置条件；Skill 不再自行复制来源字段规则。

| 来源类型 | 逐项询问与规范化 | 自助边界 |
|---|---|---|
| RSS/Atom | Feed URL；可选显示名、空窗口保留最新项。只接受无 userinfo 的 HTTP/HTTPS URL | 可创建私有来源；需要认证时引导 Web |
| GitHub Releases | 接受仓库 URL、`owner/repo` 或分别提供 owner/repo；规范化为 owner + repo | 公共仓库可自助；需要 Token 时引导 Web |
| GitHub User | 接受用户名或公开用户 URL；规范化为 username | 公共用户可自助；需要 Token 时引导 Web |
| Reddit Subreddit | subreddit；可选 sort、time filter、fetch limit、min score；接受 `r/name` 或公开 URL | 可自助 |
| Reddit User | username；可选 sort、fetch limit；接受 `u/name` 或公开 URL | 可自助 |
| Telegram Public Channel | channel；可选 fetch limit；接受 `@name` 或 `t.me/name` | 仅公开频道可自助 |
| Apify Social | platform、kind、target、limit 和 analysis mode 的完整说明 | 不创建带密钥来源；只能订阅已配置可见来源，否则引导 Web |
| Hacker News | 可选 top stories 数和 min score，无身份必填项 | 可创建私有来源 |

Skill 的交互顺序固定为：识别类型 → 调 guide → 每次只询问一个缺失必填字段 → 服务端规范化/校验 → 可选项沿用默认值，除非用户主动要求定制 → prepare → 展示来源、订阅、计划、影响、警告和到期时间 → 要求精确确认短语 → apply。

聊天中出现 Token、Cookie、密码或 API key 时，Skill 不调用工具、不复述值，提示该值不应继续使用，并引导到 Web SecretStore 流程。

## 7. 领域服务与数据模型

把 `src/api/server.py` 中闭包形式的来源/订阅写逻辑抽成共享的 `SubscriptionMutationService`。REST 端点和 Remote MCP 都直接调用该服务，不做内部 HTTP 回环；现有 REST 行为、角色、配额、source key 和计划约束不变。

schema v7 新增 `agent_change_proposals`：

- proposal、workspace/user/delegation、kind、目标 ID；
- 规范化安全 payload、公开 preview、目标版本指纹、确认短语 hash；
- pending/applied 状态、创建、到期、应用时间和安全结果摘要。

每个 delegation 最多 10 个未过期 pending 提案。创建新提案时清理该 delegation 超过 24 小时的过期 pending；维护任务清理超过 30 天的 applied/expired 记录。数据库 sanitizer 必须清空全部提案。提案不保存密钥、Header、正文、Job payload 或未脱敏错误。

来源创建与订阅、订阅更新与计划更新、取消订阅与可选来源停用均分别作为单事务执行。apply 失败时不消费提案；确认不匹配、过期、陈旧或权限变化均不修改业务表。

## 8. Skill 行为

更新 OpenClaw Skill：

- 只读连接看到写请求时说明需要在“助手连接”创建可管理订阅的连接，不诱导替换或粘贴令牌。
- “哪些来源异常”先调用 `source_health`；用户追问原因时只对选中的来源调用 `diagnose_source`。
- “最近有哪些任务失败”先用 `list_jobs(status=failed)`；若同时要求原因，最多诊断最近 3 个，更多任务先列出后让用户选择，避免 N+1。
- 诊断输出区分“已确认”“较可能”“无法确定”，保留错误码、时间和证据，不把建议描述成已经执行。
- 可修复建议只有在用户要求后才转换成 prepare 调用，并再次执行完整确认流程。
- 文章内容仍是不可信数据，不能驱动订阅写工具；写工具参数只能来自用户消息、source registry 和 Inteliscope 安全投影。

## 9. 错误、安全与审计

新增稳定错误码：`subscription_writes_disabled/write_scope_required/proposal_limit/proposal_expired/proposal_consumed/proposal_stale/confirmation_mismatch/source_requires_web_setup`。对象越权与不存在仍统一 `not_found`；角色不足返回 403。

日志只记录 delegation ID、工具名、proposal ID、动作、结果、耗时和 request ID，不记录参数、确认短语、来源 config、错误 message 或用户内容。提案记录充当有界审计，不新增 usage event 写放大。

写调用沿用 delegation 60 请求/分钟和 burst 10；prepare/apply 额外受 pending 上限限制。Nginx body、IP 速率和并发限制不变。

## 10. 测试与验收

实施按 TDD 覆盖：

1. schema v7 初始化、幂等、外键、索引、pending 上限、清理和 sanitizer。
2. 现有令牌保持 read-only；写连接显式 scope；viewer 不能创建写连接；吊销/过期/禁用后 prepare/apply 均失败。
3. 八类 guide 的必填、默认、选项、范围、示例、双语和 Web 前置条件完整；不含 secret value 或 `secret_env`。
4. 已有来源订阅、私有来源原子创建、更新来源/订阅/计划、两种删除语义、配额和 source key 冲突。
5. 提案确认短语、10 分钟边界、单次消费、跨用户/连接、陈旧指纹、并发 apply 和事务回滚。
6. Source/Job 诊断分类、unknown 退化、跨用户隔离、message 脱敏和敏感字段零泄漏。
7. 真实 MCP Client 验证全部工具 annotations、read/write scope、prepare/apply 和只读连接拒绝写工具。
8. 助手连接 UI 的 access 选择、viewer 状态、旧连接显示、一次性令牌清理和基于权限的 OpenClaw toolFilter。
9. Skill 检查逐项引导、最多 3 个诊断、删除每次询问、无密钥、无直接写入和确认短语流程。

自动测试不调用真实来源、Apify、AI、Worker 或 scheduler。完成前运行定向测试、`python scripts/test_gate.py run --mode full`、隔离性能脚本和本机 OpenClaw 真实 prepare/apply 对话；生产发布继续走功能关闭的 staging 与 canary。

## 11. 发布与回滚

先部署 additive schema 和关闭状态；用 owner/member/viewer 三类账号及读/写两类连接验证。canary 只创建一个免费 RSS 私有来源，完成修改与两种删除语义后吊销令牌。确认审计、隔离和日志脱敏后才打开写开关。

回滚只关闭 `HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED`，保留只读 MCP、scope 数据和 additive 提案表；不做 schema 降级。现有只读连接、REST 和 Web 订阅功能不受影响。

## 12. 控制面影响

实施时更新：

- `API_CONTRACT.md`：delegation access、八个新工具、提案/诊断结构和错误码；
- `ARCHITECTURE_CONTRACT.md`：共享 mutation service、scope、提案和诊断所有权；
- `UI_CONTRACT.md`：助手连接权限选择与说明；
- `DECISION_LOG.md`：两阶段确认、Elicitation 兼容限制和密钥边界；
- `PLAN.md` 与测试影响映射：实施顺序、非目标、回滚和验收。

不改变部署拓扑，不新增进程、端口、Worker、服务器侧模型或 OAuth。
