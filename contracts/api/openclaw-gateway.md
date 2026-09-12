## 5C. OpenClaw Gateway 合同

### 托管运行修复与独立分析（global 44）

- 个人 MCP 显式 `transport: streamable-http`；只允许修复完全匹配清单但缺少 transport 的旧配置，显式其他协议或归属漂移失败关闭。个人 Agent 关闭 memorySearch；主 Agent 不变。清理兼容旧协议遗漏，不重新生成正常凭据。
- 同一 managed setup/admin retry 显式修复有效绑定；GET、刷新和登录不安装配置。管理员修复已接入申请复用同一批准记录与绑定，不新增审批或扩大角色。
- global 44 `agent_analysis` 保存 binding_id/user_id/phase/objects_json/error/revision/updated_at，无历史行回填；保留已退役绑定的安装历史。`scripts/migrate_agent_analysis_v44.py` 在停止 API/Worker、备份后显式执行。
- 个人状态新增 `analysis`（phase、error、updated_at），阶段含 not_configured/preparing/configuring/catalog_ready/catalog_only/ready/no_authorized_models/failed/revoking/removed/offline。安装配置或主机返回目录不等于服务在线，必须收到机器凭据的实际能力心跳。
- 受限主机增加固定 `install_analysis` 操作，Agent=`ic-<binding_id>`、环境凭据名及私有目录由清单派生。浏览器不能指定这些目标。全主机写锁、账号授权复验和撤销墓碑共同防止旧身份复活。
- 撤销同时失效 connector 凭据、禁止领取、请求停止目标运行，清除已登记分析配置与活动环境凭据。HTTP 推理结果未知时保留结束状态标记，停止新领取且清理保持未完成；会话列表为空不能代替该 HTTP 调用结束的证据。历史目录和备份保留。
- 中继公开错误限定 MODEL_PARAMETER_UNSUPPORTED/PERSONAL_TOOLS_UNAVAILABLE/MODEL_AUTH_FAILED/MODEL_QUOTA_LIMITED/MODEL_CALL_TIMEOUT/RELAY_REQUEST_FAILED 和固定安全文案。失败事件只保留合法运行/会话标识和安全分类，不返回原始响应、路径或凭据。
- 发送/切换/重试共用同步锁；发送前通过当前会话元数据核验 Agent、模型与合法思考档位。旧快照不兼容时保留内容，不自动更换模型。分叉实际模型不符时保留原会话并提示管理员修复 Gateway，不以清空上下文替代模型切换。
- 安装版本原生协议探测与 Python MCP 直连均不能作为真实 Gateway 会话工具已加载的证明。当前 Gateway `tools.effective` 对默认内嵌运行时只读缓存，首次模型运行前可尚未初始化；项目验收须另查真实会话目录和本人工具调用。多 Agent TUI 继续要求显式 session。

### 服务端模式（2026-09-07 用户授权新增）

启用 `HORIZON_OPENCLAW_SERVER_ENABLED=true` 后，Service 返回同源 `/api/me/openclaw/socket`，浏览器以 InfoHub 登录 Cookie 连接 API；API 以固定 WSS 地址和服务端 Token 连接 Gateway。此模式替代下文浏览器直连的认证/传输边界，直连模式仍为兼容默认。

- 每个站内用户必须具有有效的个人 Agent/MCP delegation 绑定。Owner/Admin/Member 可聊天，Viewer 仅可读取已归属历史；浏览器不能指定其他用户或 Agent。缺绑定、过期、吊销、账号停用、scope 改变或上游 Agent 不存在均失败关闭，不采用 Gateway 的 default Agent。
- 检查精确 Origin/Host、登录身份、角色及当前绑定；每个请求与上游响应/事件转发前重验，空闲每 15 秒重验。每账号默认最多 12 条连接，`HORIZON_OPENCLAW_MAX_CONNECTIONS_PER_USER` 可配置 1–100，修改后重启 API；每分钟 120 个 RPC，最多 32 个待处理 RPC。连接不设总时长硬截止，仍保留心跳和身份检查。标签页关闭、离开站点或进入浏览器后退缓存时主动关闭连接并停止重连；缓存恢复后仅恢复原有连接，切换后台不主动断开，也不发送任务取消。客户端正常关闭后释放上游与计数；异常失联由传输心跳回收。
- Gateway Token 来自 `HORIZON_OPENCLAW_SERVER_TOKEN`，设备私钥保存在 `data/openclaw-relay/device.key`（0600）。浏览器不接收上游令牌或配对私钥；初始服务端设备仍由管理员配对。
- `data/openclaw-relay/ownership.sqlite3` 继续仅保存 workspace/user 与 Gateway session key 归属，不保存对话。新会话在服务端所选 Agent 下创建，fork 和写操作限定当前 Agent 的本人会话。已归属的旧 main/退役 Agent 会话只读，不迁移、不重新归属；读取历史时不强制改写原 Agent。
- 未许可 RPC、跨账号会话、跨 Agent 指定、原生 `/` 或 `!` Gateway 聊天命令均拒绝；聊天强制 `deliver:false`。不转发配置、设备管理或任意工具调用。TLS 校验、20 秒 ping、断连清理和不自动重发 chat.send 保持有效。

### 个人目录与 Skills（阶段 2）

- Relay hello 只声明上游也声明的 `sessions.preview/list` 与 `skills.status`，不伪造能力。`sessions.list` 强制当前独占 `ih-<32 hex>` Agent，允许 limit 1–100、非负 offset、至多 512 字符 search、archived false/true/all 和 updatedAt 排序；拒绝浏览器 owner/其他 Agent 参数。
- 当前个人 Agent 下的返回 key 经前缀检查后登记本人归属，冲突失败关闭；其他 Agent 返回导致请求失败，不泄露目录。只投影公开会话元数据及 totalCount/hasMore/nextOffset，不返回存储路径。旧 Agent 仅允许精确已归属 key 的查询和历史读取，不批量认领共享 main。
- `skills.status` 强制当前 Agent，可选 sessionKey 必须归属本人且属于当前 Agent；仅投影工作区已开放 Skill 的公开状态，不返回完整目录、未开放数量、路径、令牌、环境变量值或内部配置。共享服务端模式禁用浏览器直接上传、安装和修改 Skills。

### Skills 管理员开放范围（global 41）

- `workspace_agent_skill_policies` 为工作区统一清单真源，保存单调 `revision`、排序后的 `allowed_skill_keys`、`pending|synced|failed` 同步状态和安全错误码；`agent_skill_policy_syncs` 保存每个个人绑定已核验的策略版本。global 41 显式迁移为每个工作区建立 revision 1 的空清单，首次及以后新发现 Skill 均不自动开放。
- `GET /api/admin/agent-skills` 只允许实时 Owner/Admin，返回完整安全目录以及 `revision`、开放清单、同步状态和公开布尔 `sync_in_progress`；内部 attempt ID 不下发。`PUT /api/admin/agent-skills/policy` 只接受 `expected_revision` 与最多 256 个唯一安全 `allowed_skill_keys`，拒绝当前安全目录以外的键，避免伪造请求预先开放以后新发现的 Skill。版本不一致或已有同步进行中返回 `agent_skill_policy_conflict`，浏览器必须刷新后重新确认，不能覆盖另一位管理员的修改。Member/Viewer 不得读取管理目录、未开放项数量或修改策略。
- 保存先在 Service DB 持久化待同步版本并暂停该工作区所有个人绑定的新 `chat.send`，再使用独立服务端设备请求且只请求 `operator.admin`，对绑定 Agent 的 `agents.entries.<id>.skills` 做 `config.get → config.patch(baseHash, replacePaths) → config.get` 精确读回核验。凭据只从 SecretStore 的 `HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN` 取得；浏览器不能提交或读取 Token、Gateway 配置、绑定明细或管理回执。同步只替换受管个人 Agent 的 `skills` 字段。
- 全部活跃绑定核验一致后状态变为 `synced` 并恢复新聊天；失败保留同一 revision 和清单为 `failed`，返回可重试错误，不能显示保存成功或回退为全部开放。历史读取、停止操作和同步前已经开始的 run 继续有效；每次新调用及发送前按当前版本复验，旧草稿、旧页面或伪造请求不能调用已收回 Skill。
- 新绑定 manifest 携带当前清单并在部署配置中写入该个人 Agent；激活回执同时把该绑定标为当前版本已同步，未完成这一步不能开始首个聊天。普通目录、详情、`@` 和 `/skills` 缓存按用户、绑定与策略版本隔离，版本变化使旧结果失效。
- “已开放”与“可使用”分开判断。清单内 Skill 若被停用、缺依赖、受 OS、配置、工具或 Agent 条件限制，仍可显示具体公开条件，但不能选择或调用。开放不会安装依赖、写环境变量或扩大工具权限。浏览器直连个人 Gateway 继续使用其原生管理机制，不读取 Service 的工作区策略。

### 个人绑定 API 与存储（global 37）

- 托管配置补丁明确提交 `agents.ownership=explicit`，将旧 `default=true` 标记以精确 null 补丁移除；Gateway 运行时会剥离该兼容标记，不能仅依赖旧文件标记通过多 Agent 校验。保留 Agent ID、模型和其他配置，不使用隐式默认身份承接个人请求。

- 主动重新接入：`POST /api/me/agent-connection/setup/reconnect` 仅接受严格 `confirmed: true`，Owner/Admin 使用登录身份；沿用 managed 的串行化与验证。仅该显式操作允许退役已撤销绑定并创建新身份和新凭据。有效绑定复用、待验证绑定续接；普通 managed 请求不恢复撤销授权。旧 Agent、配置及历史不删除、不迁移，不复活旧 delegation。

- 本机托管接入：`POST /api/me/agent-connection/setup/managed` 只接受严格 `confirmed: true`，Owner/Admin 使用登录身份，拒绝任何额外字段。返回 202；GET 状态增加 `setup: {available,state,phase,error}`，操作状态为 idle/running/complete/failed。只读查询、刷新、重连不创建配置。错误不含内部路径、凭据或管理响应。
- 本机部署显式启用 `HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED=true` 并提供 `HORIZON_OPENCLAW_MANAGED_ROOT`；Gateway/MCP 均限 loopback，配置端口及 Gateway 实际配置路径必须匹配。该开关仅允许 loopback WS 作为现有 WSS 的本地例外，不接受远程 WS。
- 远端部署选择 `HORIZON_OPENCLAW_MANAGED_TRANSPORT=ssh`，服务端固定 SSH 主机、用户、端口、私钥和 known_hosts 文件。专用公钥只允许 `inteliscope-managed-v1` forced command，禁止通用 Shell、转发和 PTY；浏览器不能提供这些参数。Gateway 主机固定配置根及该 Service 的精确 HTTPS MCP 地址，拒绝跨部署 manifest。安装返回有签名的配置摘要回执，不传回配置或凭据；清理同步真实阶段，远端不可达不恢复本站授权。远端保留绑定撤销墓碑，旧身份不能通过重放安装复活。本地与远端共用编译、实际加载核验、MCP 本人读取及精确清理逻辑。
- 同账号只进行一次操作，主机配置通过文件锁串行化；读取哈希与本地内容检查防止覆盖配置漂移。待验证绑定继续使用同一专用凭据，已撤销绑定不复活。备份受保护；仅安装本次 Agent/MCP 与必要隔离规则，不改变其他凭据、模型或授权。Gateway 的实际应用哈希必须匹配，并校验目标 Agent 与本人 MCP 读取，才能内部生成验证回执并激活。
- 配置应用由 Gateway 的原生安全重载机制处理；未实际加载保持待验证，不强制打断活动运行。结果未知先检查再续接，不盲目重放。只在配置未改变时回滚本次凭据；不以整份旧备份覆盖后续人工修改。网页关闭不取消后台操作；服务重启保留数据库绑定，用户重试后核验续接，不自动重新配置。
- `/agents` 只保留托管接入流程。以下手动准备、下载和回执接口仅为兼容运维入口，不再从产品页面暴露；同账号不同浏览器复用服务端绑定，浏览器不存配置令牌或回执。

- `GET /api/me/agent-connection` 使用当前 Cookie，返回 `ok.data`：`state` 为 `migration_required|unconfigured|pending_verification|ready|invalid|revoked`，另含 `agent_id`、`delegation_id`、`verified_at`、`can_connect`、`can_chat`、`verification`。响应 `Cache-Control: no-store`，无 SecretStore 引用、配置路径或令牌。
- `verification.deployment/own_content` 表示受信任运维工具已校验配置并以此 delegation 成功执行 MCP 只读检查，且绑定仍有效；不是实时聊天证明。`chat/information_automations/notifications` 本阶段保持 false，后续阶段独立验收。Viewer 的 `can_chat=false`。HTTP 状态中的 `can_connect/can_chat` 还受服务端/chat 开关及 WSS URL/凭据配置有效性限制（不发起网络探测），`own_content` 受 Remote MCP 开关限制。
- `DELETE /api/me/agent-connection` 仅吊销当前账号的绑定与专用 delegation，并删除对应 Service SecretStore 值；重复调用幂等。运维工作流见[服务端操作说明](../../operations/openclaw-server.md)。
- 受信任 Owner/Admin 可为当前账号使用三个 POST：`/api/me/agent-connection/setup` 准备或恢复同一绑定、`…/setup/bundle` 下载待验证绑定的配置、`…/setup/activate` 提交回执。全部要求严格布尔 `confirmed: true`，激活另要求最多 8192 字符的 `receipt_json`；拒绝额外身份、Agent 和 URL 字段。Member/Viewer 禁止这些操作，GET 状态通过 `can_manage_setup` 表示角色资格。MCP 地址只取服务端配置，专用 delegation 保留身份，用户权限统一按实时角色计算。
- 配置下载为 `ok.data.archive_base64`（gzip tar，目录 `personal-agent` 0700，`manifest.json`/`token` 0600），响应 no-store；仅包含本人专用角色权限令牌，不含 Gateway Token 或模型密钥。前端仅在明确下载时保留内存 Blob，不写查询缓存或浏览器持久存储。主机安装仍由既有运维工具执行，网页不执行 shell 或重启 Gateway。激活沿用 HMAC/版本/一小时有效期检查；能取得配置包的管理员属于受信任运维边界，回执是运维声明而非对不可信管理员的防伪证明。已激活绑定不允许网页再次导出，失效/撤销的身份仍由运维恢复。
- `agent_connections` 保存 user/workspace、随机 binding/Agent/MCP 名称、SecretStore env 引用、专用 delegation ID、secret-free manifest、状态和部署核验时间。每用户一条、每 Agent/namespace/delegation/secret_ref 唯一；删除 delegation 后绑定失效。正文、Gateway 对话/Tasks/Artifacts 不复制进 Service DB。
- 准备绑定创建新的 `role_default` delegation，沿用 90 日过期和最多五条有效连接限制；既有用户令牌不轮换，认证时按角色生效。manifest 与 token 分文件导出到新建 0700 目录，文件 0600。Gateway 本机工具验证配置和 MCP 只读请求后产生 HMAC 回执；Service 运维 CLI 校验同 binding/manifest、签名及一小时有效期再激活。回执是受信任主机运维证据，不是恶意主机隔离或持续配置漂移检测。

### 成员接入申请（global 42）

- 显式运行 `scripts/migrate_agent_access_v42.py --data-dir … --apply`，先停止 API/Worker；迁移备份数据库且不生成历史申请。新库包含最小 `agent_access_requests` 表，现有库不自动升级。
- `POST /api/me/agent-access-requests` 只接受空对象，仅启用 Member 可申请。身份取登录账号；同账号 pending/approved 申请唯一。个人状态新增 `can_request/request_available/access_request`，不包含秘密或主机路径。
- Owner/Admin 使用 `GET /api/admin/agent-access-requests?group=pending|processing|processed&search=…&page=1`，每页 20 条，返回 items/total/pending_count，仅同工作区。`POST …/{request_id}/decision` 接受严格整数 revision、approved/rejected 和最多 200 字符 reason；拒绝必须有非空原因。事务 CAS 只允许一个决定生效。`POST …/{request_id}/retry` 接受空对象，只续接已允许申请。
- 允许提交后台配置，不表示已激活。账号、凭据及工作目录属于申请成员；写入前和激活前重新检查操作管理员和目标成员。实际加载与本人 MCP 读取验证完成才进入 ready。failed/waiting 保留 approved 与同一 binding；进程重启投影为 recovery，由管理员明确重试，不自动重放。已关联的撤销绑定不因重试复活。
- 不提升角色、开放 Skills/主机工具/模型/通知权限，不发送通知。审批状态由服务端保存，浏览器刷新和换浏览器仅查询。

### 撤销与同步清理（global 43）

- 显式离线执行 `scripts/migrate_agent_cleanup_v43.py --data-dir … --apply`；先备份，不生成历史撤销。`agent_cleanup` 保存绑定快照、操作人、申请、阶段、版本及安全错误，不保存令牌。
- 同工作区 Owner/Admin 调用 `POST /api/admin/agent-access-requests/{request_id}/revoke`，输入仅 `revision` 与 `confirmed:true`；`…/cleanup-retry` 使用清理版本。身份与对象清单来自服务端申请和绑定，重复撤销幂等。本人 `DELETE /api/me/agent-connection` 复用同一流程。
- 事务立即撤销绑定和专用 MCP 授权；旧连接每次请求校验，空闲连接沿用最长 15 秒检查。后台阶段 queued/stopping/removing/verifying/complete，失败 failed，重启投影 recovery；未完成不能重新申请或配置。失败不恢复权限，重试核对现状，仅续做未完成清理。
- 精确 Agent 会话运行使用 `chat.abort` 请求停止，普通专属 cron 停用并确认真实运行结束。仅 agentId 与 declarationKey 都精确匹配的 skillCollectionReview 派生 monitor 可例外：先在 0600 私有备份保存记录，再随目标 Agent 配置移除由 Gateway 回收，最终必须确认列表中不存在；未知系统任务、归属不明或缺少停止证据仍待清理，不直接改 cron 文件。
- 主机写锁、源文件版本校验及私有备份后，受限适配器只原子移除绑定 Agent/MCP 配置，再等待 Gateway 实际卸载与加载哈希收敛，最后删除专用环境凭据。原生 config.patch 不支持此 roster 删除，而 agents.delete 会清理会话索引，二者均不用于卸载。历史、工作目录、普通禁用任务记录及受保护备份保留；系统派生 monitor 活动记录由 Gateway 回收，备份仅作留存。新审批创建新身份，不继承旧会话；其他账号、共享凭据、模型和历史手动授权不变。

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
8. Agent Workspace 以 OpenClaw 2026.8.1 fixture 为协议基线，但 capability 只取握手 `hello.features.methods`。普通连接的 typed allowlist 为 `projects.list`、`sessions.create/list/preview/send`、`worktrees.branches`、`tasks.list/get/cancel`、`artifacts.list/get/download`、`skills.status`；请求和响应必须逐方法严格投影。`sessions.preview` 必须发送 `{keys:[exactSessionKey]}`，并只把同 key 的 `ok|empty` 视为存在、`missing` 视为已删除；`error`、缺项、重复项或畸形响应不得清除设备凭据。方法缺失为 `unsupported`，权限拒绝为 `forbidden`，不得尝试裸 RPC 或按版本号猜测。会话导航目录读取当前 Gateway 授权可访问的记录，`sessions.list` 支持 limit/offset/search/archived、updatedAt 排序和 derivedTitle/lastMessagePreview 投影，分页返回 hasMore/nextOffset/totalCount。目录展示与可信资源树分离，Tasks/Artifacts 仍只信任 exact key 与 `parentSessionKey`。显式会话切换校验 preview、目录 exact key、目标 Agent 与 describe identity 后才激活；当前产品仅提供聊天与 Skill 调用，Worktree 创建及重试在浏览器 controller 层直接返回 unsupported，不发出 RPC；既有会话读取不变，普通新对话仍可使用 `sessions.create`。
9. Artifact list/get/download 需要且只允许一个显式 `sessionKey|runId|taskId` provenance。内联预览只允许 ≤2 MiB 的安全图片或严格 UTF-8 文本/Markdown/代码；HTML、SVG、未知 MIME 仅下载。Base64 浏览器内存下载 ≤50 MiB；临时 URL 必须为当前 Gateway 映射 HTTP(S) origin 且 `expiresAt` 尚未到期。内容、URL 和 object URL 不得进入 Service、transcript 或浏览器持久缓存。
10. Skill/Cron 写入只允许独立临时 admin WebSocket：请求 exact `operator.admin`，不持久化 device credential，不自动重连，不接收普通聊天事件，并只暴露 `skills.upload.begin/chunk/commit/install/update` 与 `cron.get/list/status/add/update/remove/run/runs`。ZIP Skill 使用 Gateway 限制和 20 MiB 中较小者、SHA-256、512 KiB 顺序块及连续 offset；commit RPC 成功后才 install。Cron payload 固定 `agentTurn + isolated session + delivery none`，新建默认 disabled。所有写操作须有明确确认；共享 Gateway 不开放此临时管理入口。
11. `skills.status` 的 2026.8.1 状态投影接受 exact `skillKey`、显式 `disabled` 和 `eligible`；启用状态取 `!disabled`，不以 `eligible` 代替。兼容已有显式 `key + enabled` 状态响应，但双字段冲突必须拒绝。`missing.bins/anyBins/env/config/os`、允许列表和 Agent 过滤状态只投影公开条件；文件路径、环境变量值、原始配置均不得进入页面。未返回 ZIP 上传许可时保持上传不可用，不影响列表和详情读取。

## 模型继承兼容与安全失败诊断

OpenClaw 2026.9.2/2026.9.3 对默认模型分叉的 describe 与执行继承不一致。所有用户主动模型切换继续使用 fork=true 继承原上下文；Gateway 兼容补丁在分叉事务内将明确选择固定为 user 来源覆盖，保留原 transcript 和父关系，不改变没有显式选择时的继承。新子会话必须核验 Session/Agent/模型及覆盖来源后激活。恢复及发送前投影 parentSessionKey/modelOverrideSource：有父会话但没有 user 来源覆盖时为 unsafe_fork，身份或模型不明为 unknown，二者不能发送；再次选择相同模型也执行核对及必要的带上下文分叉。失败保留原会话，不自动发送或改成空白上下文。不增加 Gateway RPC 权限或模型调用参数。补丁只支持审阅的安装版本，由运维明确执行，Service 不自动改写安装包。

转接 chat error 优先使用受限 errorKind 分类，其次已有安全错误码，再做有界文本分类；包括 Google RESOURCE_EXHAUSTED/429、上游 502/503/504、认证和超时。输出只包含安全 errorCode/errorMessage、有效 seq、所属 Session/run 标识及白名单消息模型身份，不转发原始错误正文、URL 或管理详情。新增 MODEL_UPSTREAM_UNAVAILABLE/MODEL_CONTEXT_LIMIT/MODEL_REFUSED 兼容现有错误码；未知保留通用失败。

历史 stopReason=error 投影为 failed；通用英文错误占位改为固定中文未知原因。客户端诊断只保存安全 code/runId/actualModelId，沿用按 user/Gateway/session 隔离的有界 sessionStorage transcript；实际模型仅来自当前运行或该条历史消息的 provider/model，不从下一轮模型选择推断。远端缺失诊断不会抹去已匹配同一条消息或同一用户轮次的本地诊断；无匹配证据不拼接。无诊断显示具体原因不可用，不自动重试。

## Fast 请求选项

Fast 使用 OpenClaw 2026.8.1 `chat.send.fastMode` 布尔覆盖项，与原生 `/fast` 共用 Gateway Fast 机制但仅作用于该次请求，不发送聊天指令或调用 admin `sessions.patch`。未选择时省略参数，保留 Gateway 默认；明确关闭必须发送 false。默认只从精确 `sessions.describe.session.key` 的 `effectiveFastMode` 接受 boolean/auto（auto 显示开启），畸形或其他会话值不采用。设置按当前用户、Gateway、Session 的 Controller 生命周期隔离，新 Session 清除本地覆盖。pending/failed 重试快照保存原 bool，重试不得采用后来切换的值；成功后沿用既有清除规则。不承诺固定倍率，不自动发送真实 AI 请求验证加速。

### 角色权限配置升级与会话删除

用户绑定 manifest v3 使用统一 20 工具集合；启动时对 active v1/v2 绑定执行主机锁、身份复查和 manifest CAS 的幂等升级。只转换已知旧标准过滤器，保留 token、binding 与 delegation；失败保留待升级状态，不改成成功。成员申请和管理员审批响应均包含 `permission_profile` 与有效 `permissions`，审批不会提升账号角色。内部隔离分析凭据不参加该升级。

`sessions.delete` 仅在 hello 明确协商时可用；Controller 提交严格 `{key,deleteTranscript:true}`，不新增 REST 删除 API。Relay 只允许本人拥有、当前个人 Agent 下的非主会话，Viewer 不可写。托管 Relay 使用服务端独立 admin 连接复查唯一目录记录、显式 idle 状态和实时绑定，携带 Gateway sessionId 作为 expectedSessionId（若上游提供），再调用正式生命周期 RPC。管理凭据、上游文件路径与原始错误永不发往浏览器。成功响应投影为 `{ok:true,deleted:boolean,key?}`，key 若提供必须与请求一致；失败或未知结果不得报告成功。Gateway 负责活动资源回收；OpenClaw 2026.9.2 的工作树回收发生在会话记录删除之后，因此为满足失败时保留会话的要求，当前带工作树会话提前拒绝删除，要求先由 OpenClaw 安全清理工作树。不做本地替代清理。结构化事件使用 category=agent、action=session_delete、outcome=succeeded|skipped|failed 与 deleted 计数；未知结果记录安全错误码 session_delete_unconfirmed。
