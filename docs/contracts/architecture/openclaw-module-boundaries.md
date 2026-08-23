<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/architecture/openclaw-module-boundaries.md -->
# OpenClaw 模块所有权与依赖边界

## 1. 适用范围

本合同只定义 Browser OpenClaw、Remote MCP 与本地安装入口的代码所有权和依赖方向。部署、认证、scope、凭据、网络、事务和业务安全语义继续以 [Agent、可观测性与 ActorOps](agent-observability-actorops.md#36f-local-agent--remote-mcp-boundary) 为唯一真源；17 个 Remote MCP 工具的输入输出合同继续以 `docs/contracts/api/` 为准。

本边界不引入通用 Agent Core、capability registry、新 scope、新工具、数据库、迁移、ActorOps 或采集能力。此类变化必须在本重构稳定后另立计划和决策。

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
```

Event Router 必须先校验当前 connection generation，再对 session 事件执行 exact session 校验，对 chat/run 事件继续执行 exact run 校验。生命周期子 Controller 不互相导入，也不分别消费同一个原始 Gateway event。OpenClaw core 不导入 `workbench-live`；只有 `adapters/` 可导入 Workbench Context。UI 不直接访问 Gateway Client、原始 frame、IndexedDB、`sessionStorage` 或 `localStorage`。

`frontend/src/features/workbench-live/LazyOpenClawConversation.tsx` 只延迟加载 Adapter；`HeroWorkbenchShell.tsx` 只持有显式 Controller 类型并完成组件接线。Handoff 的 V8–V3/legacy 显示协议归 `chat/openclawHandoffProtocol.ts`，Workbench `agentContext.ts` 只保留兼容委托与自身 Context 状态。

## 4. Remote MCP 所有权

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

`AgentDelegationTokenVerifier`、`DelegationRateLimiter`、`ExactMCPPathApp`、`RemoteMCPApplication`、`SafeRemoteMCP`、`create_remote_mcp`、`RemoteMCPNotFound`、`RemoteMCPReadService` 和 `RemoteMCPDiagnostics` 的历史导入路径保持兼容。任何 façade 都不得使用通配符 re-export。

## 5. 本地安装入口所有权

`scripts/setup_openclaw_local.py` 只解析参数、调用 workflow、统一错误输出并显式保留旧导出。实现分别归 `openclaw_setup_validation.py`、`openclaw_setup_process.py`、`openclaw_setup_env.py`、`openclaw_setup_gateway.py`、`openclaw_setup_skill.py`、`openclaw_setup_mcp.py`、`openclaw_setup_compose.py` 和 `openclaw_setup_workflow.py`。

这些模块不得读取或持久化 MCP/Gateway token。测试只能使用 mock 与临时目录，不得对用户真实 `~/.openclaw`、Gateway 或 Docker runtime 执行安装、更新、重启或构建。

## 6. 可执行门禁

- `openclawImportBoundaries.test.ts` 固定外部合同、Workbench Adapter、UI/Gateway/Storage 隔离和内部无循环依赖。
- `openclawLifecycleBoundaries.test.ts` 固定单一 Event Router 与子 Controller 所有权。
- `test_remote_mcp_module_boundaries.py` 固定 composition façade、三个 registrar、17 工具并集、read/diagnostic façade 与 Remote MCP 无循环依赖。
- `test_setup_openclaw_local.py` 覆盖 CLI、退出码、校验、幂等配置更新和安全 reconcile 行为；内部模块导出不是兼容面。
- `tests/test_impact_map.json` 中 OpenClaw 专属 E2E rule 必须把 `frontend/src/features/openclaw/**` 映射到 `production-workbench.spec.ts` 与 `production-admin.spec.ts`。

尺寸目标为 `useOpenClawChat.ts ≤ 300`、`OpenClawConversation.tsx ≤ 200`、`remote_server.py ≤ 200`、`remote_diagnostics.py ≤ 200`、`setup_openclaw_local.py ≤ 150`；其他新增生产文件遵守 `tests/code_size_policy.json` 且不新增例外。
