<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/architecture/openclaw-module-boundaries.md -->
# OpenClaw 模块所有权与依赖边界

## 服务端连接扩展

用户授权的服务端模式由 `src/api/openclaw_relay_routes.py` 负责同源登录鉴权，`src/services/openclaw_relay/` 负责设备认证、RPC 白名单、会话归属与有界双向转发。浏览器通过同源 API 连接，服务端保管 Gateway 凭据；其安全合同以 `docs/contracts/api/openclaw-gateway.md` 服务端模式为准，优先于历史 browser-only 描述。

`src/services/agent_connections/` 管个人身份、SecretStore 引用、部署 manifest/回执与纯配置编译；`src/storage/agent_connection_schema.py` 管 global 37。API 只提供当前账号查询/吊销，relay 从登录身份查绑定。`scripts/manage_agent_connection.py` 只在 Service 主机准备/导出/激活；`scripts/provision_openclaw_agent.py` 只在 Gateway 主机安装/验证，不启动模型或重启服务。现有首库 bootstrap 链在全新库安装空表，旧库仅由显式迁移脚本安装。

本机托管入口由 `agent_managed_setup_routes.py` 做身份与确认校验，`agent_connections/managed_setup.py` 管账号操作生命周期与验证激活，`managed_host.py` 限制本机路径、配置锁、备份、CAS 与 Gateway 安全应用，`mcp_verification.py` 做有界只读核验。主机能力不是通用 Shell/SSH/配置编辑接口；管理连接复用独立 AgentSkillGateway，不给普通聊天连接增加 scope。后台操作展示状态保存在进程内，跨浏览器身份与重启恢复依据仍为数据库绑定及 SecretStore；未知写入不自动重放。

`src/services/agent_skill_access.py` 独占工作区 Skill 策略、revision CAS、绑定同步状态和聊天就绪判断；`src/storage/agent_skill_policy_schema.py` 独占 global 41。`src/api/agent_skill_routes.py` 只做 Owner/Admin 鉴权、公开投影与同步编排。`src/services/agent_skill_gateway.py` 是唯一可读取完整目录并修改受管 Agent `skills` 字段的服务端管理连接，凭据只来自 SecretStore，固定 exact `operator.admin`，不得导入浏览器 admin controller。`src/services/openclaw_relay/` 只消费当前允许键与聊天就绪布尔值，不能读取管理目录或修改策略。

可信小团队共用 Gateway/模型，每人独立 Agent workspace、agentDir/session 存储和 MCP namespace。每个个人 Agent 的工具 allowlist 只含自己的 13 个只读 MCP 工具；其他现有 Agent 显式 deny 新 namespace，旧共享 MCP 与各自配置保留。禁止 host/filesystem、跨会话、通知发送和全局管理工具。网关主机管理员仍是受信任主体；新建 Agent、改目录或工具配置后必须重新审查这些约束，不承诺独立主机或第三方全局插件存储隔离。

## 1. 适用范围

本合同只定义 Browser OpenClaw、Remote MCP 与本地安装入口的代码所有权和依赖方向。部署、认证、scope、凭据、网络、事务和业务安全语义继续以 [Agent、可观测性与 ActorOps](agent-observability-actorops.md#36f-local-agent--remote-mcp-boundary) 为唯一真源；17 个 Remote MCP 工具的输入输出合同继续以 `docs/contracts/api/` 为准。

本边界不引入通用 Agent Core。D179 作为 D177 之后的独立 capability 切片，在不增加工具、scope、数据库或迁移的前提下扩展 registry 来源创建，并复用现役 ActorOps v2 Binding 生命周期；未来新增工具、授权或通用 Agent Adapter 仍须另立计划和决策。

## 2. 稳定公共合同

`frontend/src/features/openclaw/openclawContracts.ts` 独占 `OpenClawChatController`、`OpenClawChatOptions`、`OpenClawChatState`、`OpenClawDomainEvent`、`OpenClawClientPort` 和 `OpenClawTranscriptPort`。外部消费者只依赖这些显式合同，不得使用 `ReturnType<typeof useOpenClawChat>`，也不得从 Hook、Gateway 或 UI 实现反推公共类型。

`frontend/src/features/openclaw/index.ts` 是 Browser OpenClaw 的显式公共 barrel；禁止通配符导出。历史入口 `useOpenClawChat.ts`、`openclawGateway.ts` 和 `OpenClawConversation.tsx` 继续作为显式兼容 façade，旧路径不得重新承载领域实现。

## 3. Browser OpenClaw 所有权

| 目录或模块 | 唯一职责 |
| --- | --- |
| `gateway/` | Gateway URL、协议类型、Device Identity 和 RPC Client；不依赖 React、Workbench 或设计系统。 |
| `storage/` | 按用户、规范 Gateway URL 和 session 隔离的偏好与 transcript 持久化；不投影 UI。 |
| `chat/` | 无 I/O 的 history、event、runtime、handoff、setup issue 与显示投影；不访问 React、网络或浏览器存储。 |
| `lifecycle/openclawChatReducer.ts` | 所有可序列化聊天 UI 状态的单一根 Reducer。 |
| `lifecycle/useOpenClawConnection.ts` | client、generation、重连 timer 与设备连接生命周期。 |
| `lifecycle/useOpenClawSessionRuntime.ts` | session key、agent/model/thinking 和 context usage。 |
| `lifecycle/useOpenClawConversationRun.ts` | run ID、send attempt、retry、abort、stream 与 media。 |
| `lifecycle/useOpenClawTranscriptController.ts` | transcript Port 编排，不拥有 Gateway event。 |
| `useOpenClawChat.ts` | 组合生命周期模块、提供唯一 Gateway Event Router，并返回 `OpenClawChatController`。 |
| `ui/` | 只消费 Controller 与 Composer Port 的 Setup、Timeline、Message、Activity、Runtime、Context、Image、Composer 和 Shell。 |
| `adapters/` | 唯一允许导入 Workbench Context 的边界，负责 DTO 映射、handoff、draft 清理与失败恢复。 |
| `workspace/` | Workspace RPC 合同、严格响应投影、capability map、事件广播与 React provider；只消费普通 Gateway client port，不访问 Service、持久存储或页面组件。 |
| `admin/` | 独立临时 admin device/socket 与固定 Skill/Cron allowlist；不导入聊天 lifecycle、transcript、Workbench 或 Service，不暴露裸 RPC。 |
| `features/agent-workspace/` | 只消费公开 Chat/Workspace Controller 与 Workbench Context，组合完整工作台；除独立 admin controller 外不访问 Gateway 实现。 |

固定依赖方向为：

```text
Gateway frame
  → useOpenClawChat 单一 Event Router
  → chat/ 纯 Domain Projection
  → lifecycle/openclawChatReducer
  → OpenClawChatController
  → ui/

Workbench Context
  → adapters/OpenClawConversation
  → OpenClaw Send / Composer DTO
  → ui/

Gateway hello.features.methods
  → workspace/ strict projection + typed controller
  → Agent Workspace resource views

Temporary operator.admin device
  → admin/ fixed Skill + Cron allowlist
  → Skills / Automations confirmation UI

Service Skill admin credential
  → agent_skill_gateway exact config synchronization
  → agent_skill_access revision/readiness
  → relay filtered skills.status + chat.send gate
```

Event Router 必须先校验当前 connection generation，再对 session 事件执行 exact session 校验，对 chat/run 事件继续执行 exact run 校验。生命周期子 Controller 不互相导入，也不分别消费同一个原始 Gateway event。OpenClaw core 不导入 `workbench-live`；只有 `adapters/` 可导入 Workbench Context。UI 不直接访问 Gateway Client、原始 frame、IndexedDB、`sessionStorage` 或 `localStorage`。

`frontend/src/features/workbench-live/LazyOpenClawConversation.tsx` 只延迟加载 Adapter；`HeroWorkbenchShell.tsx` 只持有显式 Controller 类型并完成组件接线。它在 Feed 类路由与 `/agent/**` 之间保持同一个普通 Hook、session、run、transcript 和 draft，完整工作台不得自行创建第二个普通 client。Handoff 的 V8–V3/legacy 显示协议归 `chat/openclawHandoffProtocol.ts`，Workbench `agentContext.ts` 只保留兼容委托与自身 Context 状态。浏览器直连的 Admin controller 是该模式唯一第二 WebSocket 例外：生命周期短、内存-only、无重连、无 chat event route，且不能读取 transcript 或普通 client。共享服务端模式另由后端 `agent_skill_gateway` 建立一次性管理连接；两者不共享凭据、状态或代码路径。

## 4. Remote MCP 所有权

Composer 快捷候选复用普通 Workspace Controller；`ui/useComposerShortcuts` 只解析光标与候选，`adapters/useComposerCommands` 组合现有本地确认/选择器，发送前校验归 `lifecycle/validateOpenClawSkill`。`chat/openclawSkillSelection` 拥有有界选择与历史解包，`chat/openclawSkillInvocation` 拥有纯引用格式；不得引入独立 Skill RPC 或在 UI 中操作 Gateway。Workbench `agentHandoffPrompt.ts` 单独拥有发送提示词生成，`agentContext.ts` 拥有草稿投影与状态；手动交接组件和提示词跟随交互按需加载，不能因快捷入口扩张首屏包。

`src/mcp/remote_server.py` 是 composition root：构造 Server 与 Tool Context、依次调用三个固定 registrar、完成 schema finalize 和 lifespan/HTTP 组合。它不定义工具实现、认证算法、限流算法、审计投影或业务读取。

```python
register_read_tools(server, context)
register_subscription_tools(server, context)
register_diagnostic_tools(server, context)
```

模块职责固定如下：

- `remote_auth.py` 与 `remote_rate_limit.py` 分别拥有 delegation 验证和限流。
- `remote_http.py`、`remote_call_runtime.py`、`remote_audit.py` 分别拥有精确 HTTP façade、调用边界和安全审计；审计 logger 继续使用 `src.mcp.remote_server`。
- `remote_tool_context.py`、`remote_tool_annotations.py` 分别拥有调用依赖和工具 annotations/schema finalize。
- `remote_read_tools.py`、`remote_subscription_tools.py`、`remote_diagnostic_tools.py` 只注册对应类别，不直接导入 Store 或 composition root；三者工具并集必须精确为既有 17 个。
- `remote_service.py` 是读取兼容 façade，组合 Feed、Subscription/Health 与 Job 三个 focused read service；安全公共投影归 `remote_read_projection.py`。
- `remote_diagnostics.py` 是只读诊断兼容 façade，组合 records、sanitization、classification、evidence 与 projection；纯诊断模块不导入 Store、JobQueue、RuntimeStatus 或网络 Client。
- Agent 来源能力的核心兼容 façade 为 `services/source_type_registry.py`，新增公开类型、别名、确定性账号 URL 规范化与安全 preview target 归 `services/agent_source_extensions.py`。任何当前用户可见的既有 catalog source 可按 returned ID 订阅；新建类型必须经过可逆 registry 校验，未知类型失败关闭。
- Web 与 Remote MCP 的 ActorOps 来源事务共同使用 `services/actorops/source_lifecycle.py`；`api/actorops_source_lifecycle.py` 只保留兼容导出。X/Instagram 的 Agent apply 创建 disabled source、enabled subscription 与 pending Binding 后，使用同一零网络本地对账自动收口为 ready/启用或安全 preparing；不创建 Attempt/Job 或触发远端调用，且不增加 Agent activation 工具。

`AgentDelegationTokenVerifier`、`DelegationRateLimiter`、`ExactMCPPathApp`、`RemoteMCPApplication`、`SafeRemoteMCP`、`create_remote_mcp`、`RemoteMCPNotFound`、`RemoteMCPReadService` 和 `RemoteMCPDiagnostics` 的历史导入路径保持兼容。任何 façade 都不得使用通配符 re-export。

## 5. 本地安装入口所有权

`scripts/setup_openclaw_local.py` 只解析参数、调用 workflow、统一错误输出并显式保留旧导出。实现分别归 `openclaw_setup_validation.py`、`openclaw_setup_process.py`、`openclaw_setup_env.py`、`openclaw_setup_gateway.py`、`openclaw_setup_skill.py`、`openclaw_setup_mcp.py`、`openclaw_setup_compose.py` 和 `openclaw_setup_workflow.py`。

这些模块不得读取或持久化 MCP/Gateway token。测试只能使用 mock 与临时目录，不得对用户真实 `~/.openclaw`、Gateway 或 Docker runtime 执行安装、更新、重启或构建。

## 成员申请与审批

`agent_access_routes` 只承担登录权限、输入校验和安全响应；`access_requests` 拥有工作区查询、单一开放申请和事务版本审批；`access_setup` 区分操作管理员与目标成员，复用受限 managed host 和 SecretStore。申请表通过 global 42 显式迁移，不承担通知。后台运行状态可丢弃，申请和关联绑定持久化；重启需管理员续接，不盲目重放安装。

`cleanup_store` 在同一事务记录撤销并吊销绑定/专用数据授权；`cleanup` 管理可恢复阶段和操作人复验；`cleanup_host` 只执行绑定清单内的停止和加载核验，`cleanup_config` 在检查原始配置未变化后原子移除专属条目，不调用会清理会话索引的 `agents.delete`。与接入共用主机写锁，授权撤销不等待远程锁，接入激活需再次校验未撤销。global 43 独立迁移，后台线程不自动跨重启重放。远程拒绝或证据不全时保留撤销状态与待清理记录。

## 6. 可执行门禁

- `openclawImportBoundaries.test.ts` 固定外部合同、Workbench Adapter、UI/Gateway/Storage 隔离和内部无循环依赖。
- `openclawLifecycleBoundaries.test.ts` 固定单一 Event Router 与子 Controller 所有权。
- `test_remote_mcp_module_boundaries.py` 固定 composition façade、三个 registrar、17 工具并集、read/diagnostic façade 与 Remote MCP 无循环依赖。
- `test_setup_openclaw_local.py` 覆盖 CLI、退出码、校验、幂等配置更新和安全 reconcile 行为；内部模块导出不是兼容面。
- `tests/test_impact_map.json` 中 OpenClaw 专属 E2E rule 必须把 `frontend/src/features/openclaw/**` 映射到 `production-workbench.spec.ts` 与 `production-admin.spec.ts`。

尺寸目标为 `useOpenClawChat.ts ≤ 300`、`OpenClawConversation.tsx ≤ 200`、`remote_server.py ≤ 200`、`remote_diagnostics.py ≤ 200`、`setup_openclaw_local.py ≤ 150`；其他新增生产文件遵守 `tests/code_size_policy.json` 且不新增例外。
