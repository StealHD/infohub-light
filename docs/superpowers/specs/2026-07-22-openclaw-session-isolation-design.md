# OpenClaw 测试/生产会话隔离与配对持久化设计

## 1. 背景与根因

Inteliscope 的测试站点与生产站点可以同时从浏览器连接同一台本机 OpenClaw Gateway。当前浏览器凭据已经按“Inteliscope 用户 + 规范化 Gateway URL”隔离，但所有新会话都调用：

```ts
sessions.create({ agentId, label: 'Inteliscope' })
```

OpenClaw 2026.7.1 对所有会话标签执行全局唯一校验。因此测试站点创建 `Inteliscope` 后，生产站点即使已经完成 WebSocket 连接、设备配对并获得精确的 `operator.read + operator.write` 权限，也会在 `sessions.create` 返回 `INVALID_REQUEST: label already in use: Inteliscope`。当前实现又只在建会话成功后保存设备 token，失败重试会重复配对并遗留浏览器无法复用的设备。

这与 Remote MCP、订阅写入开关和网络连通性无关。现有页面把该失败显示为权限问题也不符合真实错误。

## 2. 目标与非目标

目标：

1. 测试、生产以及同一站点的新对话可以同时连接同一 Gateway，且不会共享或争用会话。
2. 已保存 session key 的普通刷新和重连继续复用原会话，不改变历史语义。
3. 首次配对一旦成功就立即保存设备凭据，后续会话初始化失败不再触发重复设备配对。
4. 标签冲突进行一次有界自动恢复；仍失败时显示真实的会话错误，不再误报权限。
5. 保留既有 `Inteliscope` 会话和所有历史，不执行自动删除、归档、重命名或跨环境恢复。

非目标：

- 不调用 `sessions.list` 猜测或接管旧会话。
- 不把测试和生产绑定到同一个固定会话。
- 不申请 `operator.admin`，不扩大现有浏览器权限。
- 不改变 Gateway token、MCP token、Remote MCP、订阅写入、Service API 或数据库合同。
- 不自动清理此前重试产生的 OpenClaw 设备；清理必须由用户单独授权。

## 3. 已选方案

采用“可读站点来源 + 每次新会话的随机后缀”，而不是固定环境标签或从会话列表恢复：

```text
Inteliscope · rb.jiefs.top · 9f6c1d2e7a3b4c5d
Inteliscope · localhost:8080 · 32e741ac084f6d19
```

标签由当前 Inteliscope 页面的 `window.location.host` 和 `crypto.randomUUID()` 的 64 位十六进制前缀组成。标签不包含 Inteliscope 用户 ID、Gateway token、设备 ID 或其他凭据。站点来源让 OpenClaw 管理界面可区分测试与生产；随机后缀保证同一站点、同一用户的新对话和模型分支也互不冲突。

OpenClaw 仍是唯一性的最终权威。如果第一次创建返回明确的 `INVALID_REQUEST + label already in use`，客户端生成一个新标签并重试一次；其他错误不重试。第二次仍冲突时停止，避免无界创建。

没有选择以下方案：

1. 固定为 `Inteliscope-test` / `Inteliscope-prod`：只能解决两个环境的第一次创建，仍会阻断“新对话”和模型分支，也无法覆盖更多站点。
2. `sessions.list` 后按标签恢复：浏览器本地凭据被清除可能代表用户主动断开，按标签猜测会接入陈旧或其他用户的历史。
3. 删除或复用现有 `Inteliscope`：会破坏测试环境历史或造成测试/生产串会话。

## 4. 组件边界

### 4.1 会话标签模块

新增 `frontend/src/features/openclaw/openclawSession.ts`，只负责两个纯粹、可单测的能力：

- `createOpenClawSessionLabel(siteHost, randomId)`：规范化空 host 为 `browser`，从 UUID 生成 16 个十六进制字符，并返回不超过 OpenClaw 512 字符限制的标签。
- `isOpenClawSessionLabelConflict(error)`：只识别 `GatewayRequestError` 的 `INVALID_REQUEST` 标签占用错误，不把权限、网络或其他参数错误当作可重试冲突。

模块不读取凭据、不连接 Gateway、不列举会话，也不持有 React 状态。

### 4.2 Hook 会话创建入口

`useOpenClawChat.ts` 增加一个统一的有界创建入口。首次连接、模型 fork、空白回退和“新对话”全部通过该入口创建会话，不再直接写固定标签。父会话、fork、model 等原有参数原样透传；标签由入口在每次尝试时附加。

已有 `stored.sessionKey` 时不创建新会话，继续按现有流程恢复历史、模型和工具状态。

### 4.3 分阶段凭据持久化

连接顺序调整为：

1. 解析输入并读取按用户/Gateway 隔离的本地记录；
2. 完成 Gateway 握手与精确 scope 校验；
3. 取得设备 token 后，立即保存 identity、device token、scopes 以及已有的 session key（如果存在）；
4. 没有 session key 时，通过统一入口创建唯一会话；
5. 立即再次保存同一凭据记录并写入新 session key；
6. 再加载工具、历史和运行设置并进入已连接状态。

步骤 3 失败时不创建会话。步骤 4 或后续加载失败时，浏览器仍保留已配对设备，下一次连接无需再次粘贴 bootstrap token；成功创建的 session key 在步骤 5 后可供普通重连复用。

## 5. 状态、错误与安全

- `OpenClawSetupIssue.kind` 增加会话初始化类别，标签冲突提示为“OpenClaw 会话名称冲突，请重新连接”，不显示权限文案。
- 标签冲突判断必须位于通用权限/未知错误映射之前；原有 origin、protocol、scope、auth 和 network 处理不变。
- 自动重试只限一次明确标签冲突，不重试认证、权限、超时、网络、会话参数或 IndexedDB 写入失败。
- 新标签不作为恢复键；真正的恢复权威仍是按 Inteliscope 用户和 Gateway URL 保存的 session key。
- 不记录或回显 Gateway token，不把用户 ID写入 OpenClaw 标签，不扩大浏览器 scope。
- 旧版已保存的 `Inteliscope` session key 完全兼容；只有后续新建会话使用新标签。

## 6. 测试设计

实施采用 RED→GREEN：

1. 标签单测验证生产/测试 host 可读、随机后缀格式、空 host 回退、长度上限以及不同随机值产生不同标签。
2. 冲突判定单测验证只有 `INVALID_REQUEST: label already in use` 可重试，权限和其他 `INVALID_REQUEST` 均不可重试。
3. Hook 首次连接测试验证凭据在 `sessions.create` 前先保存一次，成功后再带 session key 保存；第二次连接使用已保存 device token。
4. Hook 冲突测试验证第一次冲突后使用不同标签重试并成功，连续两次冲突则停止且呈现会话错误。
5. 首次连接、模型 fork、空白回退和新对话测试都断言使用统一的来源化唯一标签，并保留各自原有参数。
6. 旧 session key 重连测试验证不调用 `sessions.create`，历史和工具加载行为不变。
7. 运行 OpenClaw 定向 Vitest、完整前端 Vitest、TypeScript、production build 和项目 `test_gate full`。

真实验收使用同一台本机 Gateway：localhost 测试站点与 `rb.jiefs.top` 各创建独立会话并保持同时在线，Gateway 日志不得再出现固定标签冲突。验收不发送模型消息、不调用付费来源，也不删除旧会话。

## 7. 发布与回滚

从 `codex/fix-openclaw-session-isolation` 构建同一 revision 的本地与 `linux/amd64` 镜像。先切换 localhost 测试环境并验证连接，再通过隔离 staging 检查 production build、live/ready、受保护 API、数据库完整性和功能开关，最后仅重建生产 API/Worker 到同一镜像；保留数据库、scheduler 状态、上一 release 和回滚镜像。

生产浏览器此前没有保存失败配对返回的 device token，因此发布后可能需要最后一次粘贴 Gateway token。新版本完成步骤 3 后，后续会话初始化失败也能使用“已配对设备重连”。

回滚只切回上一不可变镜像/release。新标签只存在于 OpenClaw 会话存储，不修改 Inteliscope 数据库；回滚后已经保存的新 session key 仍可由旧前端恢复，不要求删除新会话。

## 8. 控制面影响

实施时更新：

- `UI_CONTRACT.md`：把“一标签页一个固定 `Inteliscope` 会话”改为“按用户/Gateway 保存 session key、所有新会话使用站点来源化唯一标签”，并明确分阶段凭据保存和不自动接管旧标签。
- `DECISION_LOG.md`：记录不用 `sessions.list` 恢复、不删除旧会话以及不扩大 scope 的理由。
- `WORKLOG.md`：记录 RED→GREEN、完整门禁、本地/生产发布和真实 Gateway 验收。

不修改 `API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、Service schema、MCP 工具合同或部署拓扑。
