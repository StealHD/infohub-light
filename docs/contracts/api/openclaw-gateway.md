## 5C. OpenClaw Gateway 合同

### 服务端模式（2026-09-07 用户授权新增）

启用 `HORIZON_OPENCLAW_SERVER_ENABLED=true` 后，Service 返回同源 `/api/me/openclaw/socket`，浏览器以 InfoHub 登录 Cookie 连接 API；API 以固定 WSS 地址和服务端 Token 连接 Gateway。此模式替代下文浏览器直连的认证/传输边界，直连模式仍为兼容默认。

- 仅 owner/admin 可用；检查精确 Origin/Host、有效登录，每 15 秒重新验证登录；每账号最多三条连接，每分钟 120 个 RPC，最多 32 个待处理 RPC。
- Gateway Token 来自 `HORIZON_OPENCLAW_SERVER_TOKEN`，设备私钥保存于 `data/openclaw-relay/device.key`（0600），浏览器不接收任何上游令牌或配对私钥。
- `data/openclaw-relay/ownership.sqlite3` 仅记录用户与新建 Gateway session key 的归属，不保存对话正文，也不改变 Service DB schema。所有会话 RPC 和事件必须检查归属；未列入许可的方法拒绝转发，禁止配置/设备管理/任意工具调用 RPC，强制 chat.send deliver=false。
- 初始服务端设备需管理员部署时配对；Token 失效、未配对或协议不兼容时安全失败。连接具有 TLS 校验、20 秒 ping、断连回收及浏览器重连；不自动重发 chat.send。
- 本次不为普通成员开放共享服务端 Agent，避免共享工具权限跨账号扩大。MCP 接入是独立能力，不自动安装或启用。

### 浏览器直连兼容模式

### Composer 显式 Skill 引用

普通连接的 `skills.status` 严格投影 `userInvocable / commandVisible / modelVisible`；只有三者显式为 true、启用且 eligible、未被 Agent/allowlist 阻止、原始名称与投影一致且能唯一匹配的 Skill 可选择。不读取文件内容或路径。目录按用户 Controller、Gateway、Agent、Session 和连接代次隔离，按需读取并去重；`skills.changed` 与作用域变化失效。发送前重新读取并校验 exact key/name 和连接身份；失败保留草稿与对应失败快照。

草稿只扩展可选有界 `{key,name,gatewayUrl,agentId}`，旧 v6 草稿兼容；目录、描述和文件内容不持久化。显式调用沿用 `chat.send`：`[INTELISCOPE_SKILL_HANDOFF_V1]`、仅 name 的 JSON、单独 `$name` 行及原 V8 handoff。只接受可唯一映射的安全小写引用名，不猜别名；原问题和材料中的其他 `$` 引用被转义。禁止原生 `/skill` 工具直派和新增 `skills.run`。来源快照仍禁止工具，不能与 Skill 同发。历史投影识别该包装和 Gateway 的显式 Skill 展开前缀，只显示原 V8 展示字段；畸形包装或含私有路径的展开仅显示固定安全提示，不声称 Skill 已执行。

1. `HORIZON_OPENCLAW_CHAT_ENABLED=false` 默认关闭站内对话；`HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789` 只作为 GET delegation 响应中的公共默认值。开启后浏览器直接连接用户的 OpenClaw Gateway WebSocket v4，Inteliscope API 不接收、保存或代理 Gateway token、device token、对话、模型请求或费用。
2. 未加密 `ws://` 只允许 `127.0.0.1` 或 `localhost`；其他主机必须 `wss://`。Gateway URL 禁止 username/password、query 和 fragment。完整 dashboard 地址只允许在浏览器内解析 fragment token，规范化后的 WebSocket URL不得保留 token。
3. 初始 Gateway token 仅位于对话框内存，连接成功立即清空。浏览器使用不可导出的 Ed25519 私钥和 OpenClaw v3 device signature 配对；IndexedDB 只保存按 `Inteliscope user + normalized Gateway URL` 隔离的 CryptoKey、当前 exact `operator.read + operator.write + operator.pairing` 或 legacy exact `operator.read + operator.write` device token 与 session key。有效握手返回的 exact device credential 必须先于 `sessions.create` 持久化，session key 只在创建成功后追加；持久凭据返回 admin、approvals、缺少预期 scope 或其他额外权限时必须拒绝持久化。
4. 每个标签页最多一个普通 Gateway WebSocket。普通连接以无预设 label 的 `sessions.create` 创建 Gateway 分配的唯一 session，首条消息可触发 Gateway 自带短标题生成；不向标签写入 Inteliscope user ID，并通过按用户/Gateway 隔离保存的 session key 恢复原会话。调用 `tools.effective` 单独判断 MCP/Skill 可用性，并支持 `chat.history`、流式 `chat` event、`chat.abort`、断线重连和新 session。`models.list(view=configured)` 的裸 ID 必须先规范化为 `provider/model`，模型分叉创建后必须由 `sessions.describe` 验证再切换；可选推理档位只取该模型目录条目或精确当前会话的 `sessions.describe.thinkingLevels`，不得用 `agents.list` 的 Agent 级档位补造未知模型能力。上下文用量只可通过已知当前 session key 精确筛选 `sessions.list` 并订阅 `sessions.changed`；不得按 label 发现、推断或收养其他 session，且 `totalTokensFresh=false`、非正数或缺失容量不得在浏览器估算。`chat.send` 必须使用唯一 idempotency key 和 `deliver:false`；消息最多显示 100 条、总文本 100,000 字符。
5. Browser Agent 上下文通常最多包含八条有序安全记录。Feed 记录只含 `articleId/title/sourceName?/publishedAt?/sourceUrl?`；运行记录可附带安全显示状态，但内部 `job_id`、UI detail/error 不得成为可见历史。可选 `sourceUrl` 只允许无凭据 HTTP(S)，在草稿、transcript 和 handoff 前移除 fragment、跟踪参数与敏感 query 并限制 2,048 字符。V8 handoff 保留既有 `context_readonly` 与 `direct`，并新增 `source_snapshot_readonly`：专题入口一次替换旧附件、保留未发送问题，把当前过滤结果中最多 100 篇的来源名、窗口、标题、已有摘要和时间压缩为不超过 32,000 字符的 V6 浏览器草稿；标题/摘要中的网址会被移除，快照不包含 URL、媒体、metadata 或正文。该模式只把快照作为不可信只读证据发给 Gateway，禁止 `get_item`、`web_fetch`、其他补充工具与任何写操作，证据不足时明确未知；Viewer 可继续使用该只读 Agent 能力。浏览器投影继续兼容 V7、V6、V5、V4、V3 和旧无版本 handoff，且不得显示内部指令或 ID。其他上下文模式、图片边界、订阅 proposal 流程、失败重试和 Remote MCP 正文读取规则保持不变。
6. Gateway 可选的 `agent/lifecycle/tool/thinking` 运行事件只可投影到当前标签页、当前 exact session key 和当前 run ID。浏览器按单调序号及 tool-call ID 去重，且只把事件映射为前端固定阶段和中文白名单动作；`thinking` 永远只显示通用的“正在思考”，未知工具只显示“正在使用工具”。浏览器不得渲染、写入 transcript、sessionStorage、IndexedDB 或 Service 的原始思维、工具参数、工具结果、meta、原始错误、URL、令牌或确认短语。运行轨迹只在当前页面会话内存中存在，完成后折叠；Gateway 未协商该能力时，`chat.send` 仍必须立即生成本地可信的处理中状态，不得回退为首段回复前空白。
7. 图片输入只在 `image_io_enabled=true` 且当前 `models.list.input` 显式含 `image` 时启用；它使用既有 `chat.send.attachments`，不依赖 `chat.media.ticket`。浏览器把 JPEG/PNG/WebP 在内存中规范化为最多四张、单张 5 MiB、总计 12 MiB、40 MP 输入及最长边 2048 px 的 Base64 attachment；浏览器以 `chat.send.attachments` 直送 Gateway，Service 不接收图片。图片输出和历史只保存 `messageId + partIndex` 媒体引用；只有 Gateway capability 含 `chat.media.ticket` 且返回路径属于 `media_origins` allowlist 时，浏览器才为每张图片调用 `chat.media.ticket{sessionKey,messageId,partIndex}` 并渲染返回的短期票据。票据不得持久化，刷新、重连或加载失败后重新申请；任意正文外链、`file:`、协议相对 URL、非法路径或 MIME 都不得渲染。缺少票据 RPC 时继续支持文本和图片输入，但不显示 Gateway 输出/历史图片。
8. Agent Workspace 以 OpenClaw 2026.8.1 fixture 为协议基线，但 capability 只取握手 `hello.features.methods`。普通连接的 typed allowlist 为 `projects.list`、`sessions.create/list/preview/send`、`worktrees.branches`、`tasks.list/get/cancel`、`artifacts.list/get/download`、`skills.status`；请求和响应必须逐方法严格投影。`sessions.preview` 必须发送 `{keys:[exactSessionKey]}`，并只把同 key 的 `ok|empty` 视为存在、`missing` 视为已删除；`error`、缺项、重复项或畸形响应不得清除设备凭据。方法缺失为 `unsupported`，权限拒绝为 `forbidden`，不得尝试裸 RPC 或按版本号猜测。会话导航目录读取当前 Gateway 授权可访问的记录，`sessions.list` 支持 limit/offset/search/archived、updatedAt 排序和 derivedTitle/lastMessagePreview 投影，分页返回 hasMore/nextOffset/totalCount。目录展示与可信资源树分离，Tasks/Artifacts 仍只信任 exact key 与 `parentSessionKey`。显式会话切换校验 preview、目录 exact key、目标 Agent 与 describe identity 后才激活；Worktree 项目与 base ref 必须分别再次匹配 `projects.list` 与 `worktrees.branches`。新任务只用 `sessions.create`，不存在 `tasks.create`。
9. Artifact list/get/download 需要且只允许一个显式 `sessionKey|runId|taskId` provenance。内联预览只允许 ≤2 MiB 的安全图片或严格 UTF-8 文本/Markdown/代码；HTML、SVG、未知 MIME 仅下载。Base64 浏览器内存下载 ≤50 MiB；临时 URL 必须为当前 Gateway 映射 HTTP(S) origin 且 `expiresAt` 尚未到期。内容、URL 和 object URL 不得进入 Service、transcript 或浏览器持久缓存。
10. Skill/Cron 写入只允许独立临时 admin WebSocket：请求 exact `operator.admin`，不持久化 device credential，不自动重连，不接收普通聊天事件，并只暴露 `skills.upload.begin/chunk/commit/install/update` 与 `cron.get/list/status/add/update/remove/run/runs`。ZIP Skill 使用 Gateway 限制和 20 MiB 中较小者、SHA-256、512 KiB 顺序块及连续 offset；commit RPC 成功后才 install。Cron payload 固定 `agentTurn + isolated session + delivery none`，新建默认 disabled。所有写操作须有明确确认；共享 Gateway 不开放此临时管理入口。
11. `skills.status` 的 2026.8.1 状态投影接受 exact `skillKey`、显式 `disabled` 和 `eligible`；启用状态取 `!disabled`，不以 `eligible` 代替。兼容已有显式 `key + enabled` 状态响应，但双字段冲突必须拒绝。`missing.bins/anyBins/env/config/os`、允许列表和 Agent 过滤状态只投影公开条件；文件路径、环境变量值、原始配置均不得进入页面。未返回 ZIP 上传许可时保持上传不可用，不影响列表和详情读取。

## Fast 请求选项

Fast 使用 OpenClaw 2026.8.1 `chat.send.fastMode` 布尔覆盖项，与原生 `/fast` 共用 Gateway Fast 机制但仅作用于该次请求，不发送聊天指令或调用 admin `sessions.patch`。未选择时省略参数，保留 Gateway 默认；明确关闭必须发送 false。默认只从精确 `sessions.describe.session.key` 的 `effectiveFastMode` 接受 boolean/auto（auto 显示开启），畸形或其他会话值不采用。设置按当前用户、Gateway、Session 的 Controller 生命周期隔离，新 Session 清除本地覆盖。pending/failed 重试快照保存原 bool，重试不得采用后来切换的值；成功后沿用既有清除规则。不承诺固定倍率，不自动发送真实 AI 请求验证加速。
