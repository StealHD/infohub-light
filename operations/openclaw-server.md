# OpenClaw 服务端连接

成员自动接入、审批及撤销的跨主机部署使用[远端托管操作说明](openclaw-managed-remote.md)。下文手动包流程仅为兼容运维方式，不是用户接入入口。

在生产 `.env` 配置：

```dotenv
HORIZON_OPENCLAW_CHAT_ENABLED=true
HORIZON_OPENCLAW_SERVER_ENABLED=true
HORIZON_OPENCLAW_SERVER_URL=wss://www.senjee.top:4430
HORIZON_OPENCLAW_SERVER_TOKEN=<通过安全通道写入当前 Gateway Token>
```

Token 不写入 Git，不从浏览器下发。API 上线前将部署用设备私钥放入 `data/openclaw-relay/device.key`（目录0700、文件0600），并在 Gateway 批准这一个设备的 operator.read/operator.write。不可批准未知设备或关闭鉴权。

Skills 开放范围使用另一条后端管理连接。把专用 Gateway Token 通过 SecretStore 写入 `HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN`，不要加入 `.env`、JSON、浏览器表单或命令参数：

```bash
python - <<'PY'
from getpass import getpass
from src.services.secret_store import SecretStore
SecretStore('/absolute/service/data').set('HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', getpass('Skill admin token: '))
PY
```

首次同步会在 `data/openclaw-relay/skill-admin/` 建立独立设备身份；只批准该设备的 exact `operator.admin`，不得给普通 relay 设备增加 admin scope。管理员保存清单时，Service 只修改已绑定个人 Agent 的 `agents.entries.<id>.skills`，并读回核验；删除或轮换此 Secret 会让策略保持待重试/失败且暂停新聊天，不会回退为全部开放。

此模式要求个人绑定，Owner/Admin/Member 可聊天，Viewer 只读。API 的 `/api/me/openclaw/socket` 需由同源 Nginx 转发 WebSocket Upgrade/Connection，read timeout 至少60秒；公网不需要增加浏览器到 Gateway 的 IP 白名单。Gateway 白名单只放行 API 服务器出口。

浏览器刷新后会显示服务端连接说明；以前保存的直连地址不会覆盖服务端模式。会话恢复索引只存在当前用户 sessionStorage；Gateway 凭据不在浏览器保存。不同用户的会话由独立归属表强制隔离。当前模式提供普通对话、历史恢复和模型选择；尚未开放工作区管理、自动化、产物和全局会话目录 RPC。上线验证应覆盖匿名/Origin/角色拒绝、跨账号会话拒绝、Cookie过期断开、模型列表、无外发 chat.send、API/Worker readiness。

回滚：保留归属数据和私钥，设置 `HORIZON_OPENCLAW_SERVER_ENABLED=false` 并恢复上一镜像；兼容模式重新使用 `HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL`。不要删除原有 Service 数据。HTTPS证书手动DNS续期不由本功能接管。

## 个人 Agent 部署（阶段 1，仅受控环境）

以 OpenClaw 2026.9.2 验证。正式生产发布在 PLAN 阶段 6；以下路径必须指向当前目标环境。Service 主机与 Gateway 主机分别执行，不把浏览器登录、Gateway Token 或模型凭据传入 manifest。

1. 停止目标 API/Worker，先预览、再显式应用迁移；保留工具输出的备份供回滚：

   ```bash
   python scripts/migrate_agent_connections_v37.py --data-dir /absolute/service/data
   python scripts/migrate_agent_connections_v37.py --data-dir /absolute/service/data --apply
   python scripts/migrate_agent_skill_policy_v41.py --data-dir /absolute/service/data
   python scripts/migrate_agent_skill_policy_v41.py --data-dir /absolute/service/data --apply
   ```

   global 41 依赖 global 40 且初始化为空清单，不从 Gateway 现有目录推断授权。完成迁移和管理设备配对后，Owner/Admin 在 Skills 页明确选择并同步；在此之前新的 `chat.send` 失败关闭。回滚镜像前保留 global 41 表和备份，不删除策略或把空清单解释为全部开放。

2. Service 主机上为一个启用账号准备绑定，再导出到尚不存在的目录。账号 ID 从该环境的成员记录取得；MCP 地址必须为同一 Service 的 HTTPS `/mcp`，本地测试允许 HTTP loopback。受信任 Owner/Admin 为本人配置时，也可在 `/agents` 的“配置个人 Agent”确认准备并下载配置包，解压后用于下列主机安装步骤；网页不会修改已有数据连接或启动模型。普通成员仍使用本节 CLI。

   ```bash
   python scripts/manage_agent_connection.py prepare --data-dir /absolute/service/data --user-id USER_ID --mcp-url https://service.example/mcp
   python scripts/manage_agent_connection.py export --data-dir /absolute/service/data --user-id USER_ID --bundle-dir /private/new-bundle
   ```

3. 经已有 SSH 安全传送 bundle 到 Gateway 主机，保持目录 0700、token 0600。Gateway 上执行 `python scripts/provision_openclaw_agent.py install --root /absolute/.openclaw --bundle-dir /private/new-bundle`。工具校验配置后原子安装，备份原配置，Token 写入该根目录 `.env` 的独立 SecretStore 引用。重复安装必须符合原策略；同名 MCP、目录重用、符号链接、配置漂移会失败。现有 main/其他 Agent 会增加该个人 MCP 的禁止规则；无显式 ownership/default 的旧配置增加 main 兼容默认标记，保留原默认路由。不自动迁移 include、legacy agents.list 或自定义 session.store；会话存储必须沿用 Gateway 按 Agent 分目录的默认路径，拒绝目录符号链接。自定义根目录启动 Gateway 时，OPENCLAW_STATE_DIR 必须指向同一根目录。
4. 按目标环境已有服务管理方式加载配置/重启 Gateway，然后执行 `python scripts/provision_openclaw_agent.py verify --root /absolute/.openclaw --bundle-dir /private/new-bundle --receipt /private/receipt.json`。检查只包括真实配置验证、个人工具许可及 MCP initialize/tools.list/list_subscriptions，不调用模型。回执包含完整配置指纹，配置内容和凭据不写 stdout；失败只输出错误类型。
5. 将 receipt 安全传回 Service 主机，一小时内执行 `python scripts/manage_agent_connection.py activate --data-dir /absolute/service/data --user-id USER_ID --receipt /private/receipt.json`，或由准备本人绑定的 Owner/Admin 在“继续配置”上传回执激活。`status` 子命令及登录后的 `GET /api/me/agent-connection` 可查结果。relay 每次连接另核验上游确有该 Agent；真实聊天仍需单独验收。删除临时导出 Token 由运维完成，勿纳入 Git、聊天或共享附件。

吊销可在站内 DELETE 当前绑定，或运维执行 `revoke`。账号停用、delegation 过期/吊销/删除、scope 改变都会阻断新请求及晚到响应。修复时先 `retire` 吊销并移除 Service 绑定，再从 prepare 重建新身份；旧 Agent/session 目录由运维保留，不能复用给其他账号。旧会话仍按已有归属只读。已有其他 delegation 不被修改。

Gateway 主机属于可信运维边界；部署后变更任何 Agent、工具或全局插件必须重新检查隔离。Service 的部署回执不代表运行中配置不会被主机管理员修改，也不代表聊天、提醒或通知已验收。

## Codex 独立分析的模型目录超时（本地修复记录）

2026-09-09 本机 `@openclaw/codex 2026.8.1` 的独立分析在调用模型前失败。实际异常是 `CodexAppServerLocalRequestCancellationError: model/list timed out`，外层包装为 `LLM_COMPLETION_FAILED`，Service 因此显示 `analysis_call_failed`。插件目录已可读取不代表新建独立执行客户端能在 5 秒内完成目录准备。

已在实际加载的独立 Codex 插件包应用[版本限定补丁](patches/codex-2026.8.1-model-list-timeout.patch)：仅 `isolated completion` 的 `model/list` 等待上限改为 30 秒，其他 bounded turn 仍为 5 秒；等待继续受调用方总超时和 AbortSignal 限制，不新增重试或模型回退。未调整模型权限、工具隔离、通知和 Service API。

维护时先确认运行进程加载的 `@openclaw/codex` 包路径及 package 版本，不能只修改 OpenClaw 安装目录中的同名内置文件。对目标包先执行补丁 dry-run，成功后应用并按现有服务管理方式重载；以实际加载源包含 `modelListTimeoutMs` 确认生效。回滚使用同一补丁的反向 dry-run/apply 后重载。插件升级或 generation 更换后必须重新核对，不自动向未知版本套用此补丁；本记录不代表 VPS 已部署。

验证证据：修复前捕获到准备阶段 5 秒超时；修复后同一条规则、同一篇文章通过独立调用，14.7 秒返回 HTTP 200，实际模型为 `openai/gpt-5.6-terra`，结果 `matched`，单篇覆盖与原文引用通过 Service 的 `batches.validate`。受控检查覆盖慢目录、其他调用的原上限、总时限、30 秒上限及无自动重试。诊断没有写回历史失败记录，也未发送通知；页面再次提交被审批拦截，未宣称页面端到端测试通过。
