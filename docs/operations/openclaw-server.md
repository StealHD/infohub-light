# OpenClaw 服务端连接

成员自动接入、审批及撤销的跨主机部署使用[远端托管操作说明](openclaw-managed-remote.md)。下文手动包流程仅为兼容运维方式，不是用户接入入口。

## WebSocket 稳定性与诊断

生产 Nginx 对 `/api/me/openclaw/socket` 使用独立 Upgrade location、关闭代理缓冲，并将读写超时保持为 3600 秒。浏览器和 Relay 另有应用级 `relay.ping`，因此不要通过继续放大代理超时掩盖断线。

`deploy/nginx/inteliscope-rate-limit.conf` 中的 `inteliscope_websocket` 日志格式只记录时间、API 握手返回的 request ID、代理/上游状态与耗时；站点配置将其写入 `/var/log/nginx/inteliscope-websocket.log`。用同一 `request_id` 查询 API runtime 日志，可看到 `stage`、安全关闭码和持续时间。不要在该日志格式中加入 URI、Cookie、Authorization、查询参数或消息正文。

排查顺序：先确认 API/Worker 容器没有重启或 OOM，再按 request ID 区分 `browser_transport`、`upstream_connect|upstream_auth|upstream_transport`、`agent_verify` 与 `session_watch`。浏览器 1000/1001 是正常离开；1008 表示登录或绑定已失效并需要人工处理；1011 和握手 5xx 属于可恢复链路故障。修改 Nginx 后先运行 `nginx -t`，再 reload；保留修改前配置以便回滚。

`browser_transport` 的 1006 只说明连接没有正常完成关闭握手，不能单凭它认定是浏览器、Nginx 或上游故障。若多条连接同时中断，应核对客户端 VPN/代理的实际路由，并对同一站点、同一时段做代理路径与直连路径的持久连接对照；只请求 `/api/health/live`，不发送聊天或重放写操作。结合断线时间和仅含 TCP 关闭标志的抓包确定故障所在链路，不采集 Cookie、报文正文或 TLS 密钥。

确认客户端代理路径异常且 HTTPS 直连稳定后，可为该站点添加精确域名直连规则，例如 Clash 的 `DOMAIN,rb.jiefs.top,DIRECT`，保存到当前订阅的规则覆写文件并核对运行时命中。保留原配置以便撤销；无需改变其他站点路由、关闭 TLS 校验或继续加大服务端超时。以实际浏览器连接持续至少 30 分钟、期间仍有双向流量且没有新增异常断线为验收证据；重连提示出现本身不代表故障已修复。

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

## 受管浏览器控制端点被策略拦截

`browser endpoint blocked by policy` 指 CDP 控制端点被拒绝，不是目标网页拒绝访问。若 `browser.ssrfPolicy.blockedHostnames` 包含本机 CDP 使用的 `127.0.0.1/localhost/::1`，即使已开放 `browser` 工具，浏览器也不能启动。不要只删除黑名单并保留 `dangerouslyAllowPrivateNetwork=true`，这会放开网页对本机与私网的访问。

服务端运维命令 `python scripts/repair_openclaw_browser_policy.py --data-dir /absolute/service/data` 默认只读取配置并输出预览及 `base_hash`，不输出配置、地址或凭据。使用既有 Service 环境与 SecretStore 的 Skill 管理凭据。工具只接受本机托管的浏览器配置；远端 CDP、附加已有浏览器、自定义信任/允许清单及未知策略字段要求单独人工审查。

若 `extraArgs` 包含 `--proxy-server`、`--proxy-pac-url` 或 `--proxy-auto-detect`，命令在预览及应用前均拒绝改写，并说明代理与严格策略不兼容；即使此前已移除 loopback 黑名单，也不能以 `unchanged` 表示这条导航链路可用。不要为消除该错误打开私网放行，或移除业务必需代理。需先核对 Skill 在原生 Agent 与个人 Agent 下实际使用的脚本、工具和浏览器隔离方式，准备兼容的执行环境。

预览有变更时，修复会关闭新旧两种私网放行开关，移除显式 loopback 冲突项，保留 metadata 和其他域名禁止项。网页导航、DNS 解析到私网及重定向继续受 OpenClaw 原生严格 SSRF 检查约束；固定本机 CDP 通过原生端点专用校验。该策略属于整个 Gateway 的浏览器配置，会限制所有 profile 的私网页面访问，不能用于需要私网站点的共享部署。

只有获得配置应用授权后，才使用同一命令加 `--apply --expected-hash <预览的base_hash>`。命令使用 `config.patch` 的 CAS 和精确 `browser.ssrfPolicy.blockedHostnames` 数组替换，写后读回核验，不调用模型、启动浏览器、自动重试或强制重启 Gateway。`saved_pending_reload`（退出码 2）只表示保存后尚未证明加载，需另查实际加载状态；未知写入结果应检查配置，不能盲目重放。`applied` 只证明配置已加载，真实浏览器和 Skill 仍需单独验收。普通应用发布、Skills 同步、成员接入及 GET 不会自动运行此修复。

验收必须包含独立测试标签页的实际公网域名导航、页面读取及测试页清理，随后通过个人 Agent 验证目标 Skill；启动成功、CDP ready 或原生 `main` 的成功记录均不能替代这两步。关闭代理也不等于域名导航可用：部分 OpenClaw 版本在显式严格模式下还要求 IP 字面量或经过审核的域名允许项。遇到此限制应如实记录，不扩大信任来绕过验收。

### 需要代理的独立托管浏览器

Linux Gateway 可显式安装 `scripts/openclaw_browser_egress/` 中的运行环境。先在本地审查和测试，再把这三个 Python 文件传到 Gateway 的独立临时目录；它不是 Inscope 镜像构建，也不读取原生 main 的浏览器数据。主机需 Python 3、Chrome、sudo、systemd 和 nftables。

```bash
python3 install.py --gateway-user ubuntu --cdp-port 18802
sudo python3 install.py --gateway-user ubuntu --cdp-port 18802 --apply
```

默认上游代理为本机 HTTP 7890，新出口代理监听本机 18890。安装器创建无登录账号 `inteliscope-browser`、独立目录 `/var/lib/inteliscope-browser`、三个 systemd 服务和固定启动器 `/usr/local/bin/inteliscope-managed-chrome`；只改自己的 `inet inteliscope_browser` 表。旧安装文件备份到输出的 `/var/backups/browser-egress-*`，其 manifest 记录原文件映射。安装会启动新的独立浏览器，不修改 Gateway 配置、不重启 Gateway、不停止原生 main 浏览器。

必须先以该独立账号验证：直连公网及 localhost/内网/metadata 均被内核拒绝；通过 18890 访问这些私网目标也被代理拒绝；公网 HTTPS 可经代理打开。代理只允许 443 CONNECT，检查全部 IPv4 解析结果并固定上游 IP，拒绝私网、回环、链路本地、保留和多播地址；不支持 HTTP、IPv6 目标或其他端口。浏览器启动前重新原子应用出口规则；规则/代理不可用时启动失败，不退回直连。每条隧道空闲上限 60 秒、总时长 300 秒。

验收后，由管理员备份并 CAS 修改受管 profile 的 `cdpPort`、全局及 profile `executablePath` 为该启动器、`attachOnly=true`，并将 `extraArgs` 指向 18890。浏览器由 systemd 管理，Gateway 只附加到此固定 CDP 端点；不通过 sudo 子进程规避 Gateway 的启动 PID 归属检查。OpenClaw 代理兼容模式需 `dangerouslyAllowPrivateNetwork=true`；这里只允许在上述独立账号、固定启动器与出口限制全部有效时使用，网络权限仍由内核和代理限定为公网 HTTPS。保留 metadata 禁止项，不能将此配置复用给普通 Chrome 或原生 main 浏览器。核对配置加载后，再执行 Gateway 实际导航/读取及个人 Agent Skill 验收。

站点验收还需核对 Skill 的个人 Agent 入口与原生脚本当前维护的入口一致。部署中的 `book-skill` 在 `Project Agents` 小节指定 `openclaw` profile 和已核验的首页，要求通过可见搜索控件操作；不要让模型凭记忆猜旧域名。修改前备份两个已安装目录的说明，保留 main 工作流及脚本不变。DNS/代理路由变化、站点验证或登录仍是独立结果，不能由工具调用成功推断已取得书籍结果或下载链接。

OpenClaw 会自动补充 `user`、`chrome` profile。切换时必须显式将这两个名字也配置为 `driver=openclaw`、`attachOnly=true`、相同隔离 CDP 端口，并核验实际 profile 列表；不能留下能附加到账号原有桌面的默认入口。其他既有 profile 需要逐个确认，不支持混合共享部署。原生 main 的专用脚本直连自己的独立端口，不受这些别名替换影响。

回滚先将 Gateway 配置恢复到备份并核对加载，停止此次独立浏览器，再停止新代理服务；使用安装备份恢复自己的文件。只清理 `inet inteliscope_browser` 表，保留原生浏览器、其他防火墙规则和用户数据。不得在该独立浏览器仍运行时移除出口限制。

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

2026-09-13 再次发生相同的 `model/list timed out`：升级后当前加载的是 `@openclaw/codex 2026.9.3` 的新 generation，旧版插件上的补丁没有随之迁移。先用 `openclaw plugins inspect codex --json` 核对实际 `rootDir`，再运行 `python scripts/patch_openclaw_codex_model_list_timeout.py` 检查当前加载包；返回 `ready` 后加 `--apply`，按主机现有服务管理方式重启 Gateway。脚本默认从插件检查结果定位实际加载包，只接受已核对的 2026.9.3 源码，备份原文件；升级到未知版本时拒绝套用。重启后再次运行检查，应返回 `already_patched`。本机对照验证：5 秒时测试失败；同一任务、同样文章在 30 秒上限下由网页完成分析，进度 1/1 且显示命中依据。此操作只修复本机已加载的插件，不代表 VPS 已修改。
