# Inteliscope Nginx Basic Auth 发布配置

适用于 `vps-tokyo`：Nginx 为 `rb.jiefs.top` 提供 80/443，反代到本机 `127.0.0.1:8080`，整站先经过 Basic Auth，再进入应用登录。

## 1. 确认 Docker 只监听本机

`.env` 建议保持：

```bash
HORIZON_WEB_BIND=127.0.0.1
HORIZON_WEB_PORT=8080
```

然后重启：

```bash
./scripts/up-latest.sh
docker compose ps
```

这样公网不能绕过 Nginx 直接访问 `:8080`。

## 2. 生成 Basic Auth 密码文件

使用 `openssl` 生成 Apache MD5 格式密码：

```bash
USER_NAME=friend
sudo sh -c 'printf "%s:%s\n" "$1" "$(openssl passwd -apr1)" >> /etc/nginx/.htpasswd_inteliscope' sh "$USER_NAME"
sudo chmod 640 /etc/nginx/.htpasswd_inteliscope
```

命令会提示输入密码。需要多个朋友共用账号时，只生成一个账号即可；需要多个账号就重复执行并换用户名。

如果服务器有 `htpasswd`：

```bash
sudo htpasswd -c /etc/nginx/.htpasswd_inteliscope friend
sudo htpasswd /etc/nginx/.htpasswd_inteliscope another_friend
```

## 3. 启用 Nginx 站点

复制模板：

```bash
sudo cp deploy/nginx/inteliscope-basic-auth.conf /etc/nginx/sites-available/inteliscope
sudo ln -sf /etc/nginx/sites-available/inteliscope /etc/nginx/sites-enabled/inteliscope
```

编辑域名：

```bash
sudo nano /etc/nginx/sites-available/inteliscope
```

模板已使用 `rb.jiefs.top` 和 VPS 当前证书路径。另将登录限流配置安装到 Nginx `http` 上下文：

```bash
sudo cp deploy/nginx/inteliscope-rate-limit.conf /etc/nginx/conf.d/inteliscope-rate-limit.conf
```

检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 4. 验证

本机应能访问后端：

```bash
curl -I http://127.0.0.1:8080
```

公网域名未带账号密码应返回 `401`：

```bash
curl -I http://你的域名
```

带账号密码应返回 `200`：

```bash
curl -I -u friend:你的密码 http://你的域名
```

## 注意

- Basic Auth 会保护整站，包括信息流和配置页。
- 账号密码会被浏览器缓存；朋友退出通常需要关闭浏览器或访问无效账号覆盖缓存。
- 强烈建议配合 HTTPS 使用，否则 Basic Auth 密码会以可被中间人解码的形式传输。
- Basic Auth 不能替代应用登录和 owner/admin/member/viewer 权限。访问站点会先过 Nginx Basic Auth，再使用个人应用账号登录。

## Remote MCP

Remote MCP 必须使用精确的 `/mcp` location。该 location 关闭浏览器 Basic Auth，改由应用验证每位用户的一次性 Bearer 令牌；同时限制 256 KiB 请求体、每 IP 120 请求/分钟和 8 个并发连接，并显式透传 `Authorization`。

生产启用前设置：

```bash
HORIZON_REMOTE_MCP_ENABLED=true
HORIZON_REMOTE_MCP_PUBLIC_URL=https://rb.jiefs.top/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED=false
HORIZON_REQUIRE_WORKER_FOR_READINESS=false
```

只读生产发布只启动 `horizon-api`，不得启动 Worker 或 scheduler。两个写开关保持 `false`；本地只允许使用类似 `http://127.0.0.1:8080/mcp` 的 loopback URL。系统参数写入还要求先显式应用 global31 迁移。回滚时先关闭功能开关，再移除 Nginx 的精确 location；schema v6 delegation、schema v7 proposal 与 global31 system settings additive 表均保留。

## 浏览器直连 OpenClaw

站内对话由用户浏览器直接连接自己的 OpenClaw Gateway，Inteliscope 和 Nginx
不代理 Gateway WebSocket。默认保持关闭：

```bash
HORIZON_OPENCLAW_CHAT_ENABLED=false
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789
HORIZON_OPENCLAW_IMAGE_IO_ENABLED=false
HORIZON_OPENCLAW_MEDIA_ORIGINS=
```

本机只允许 `ws://127.0.0.1` 或 `ws://localhost`；远程 Gateway 必须使用
`wss://`。站点 CSP 的 `connect-src` 只开放本站、上述 loopback Gateway 和
`wss:`，并通过 `frame-ancestors 'none'` 禁止页面嵌入。生产开启前必须把
Inteliscope 的完整 Origin 追加到 OpenClaw 的
`gateway.controlUi.allowedOrigins`，保留原有条目，禁止使用 `*`。

```bash
HORIZON_OPENCLAW_CHAT_ENABLED=true
```

该开关只改变浏览器对话面板；服务器仍不运行 Agent、模型或 OpenClaw，
订阅写开关继续保持 `false`。

### 安全图片与云端 Gateway

图片能力默认关闭，且必须先发布包含 `chat.media.ticket` 的 OpenClaw Gateway 版本。
该 RPC 只会对当前会话、消息和图片内容块签发 5 分钟票据；浏览器只渲染这个
票据返回的路径，绝不使用消息正文中的外链或本地文件路径。

本机 Canary 可显式配置：

```bash
HORIZON_OPENCLAW_IMAGE_IO_ENABLED=true
HORIZON_OPENCLAW_MEDIA_ORIGINS=http://127.0.0.1:18789
```

云端建议把 WebSocket 和媒体放在同一 Gateway Origin，例如
`wss://openclaw.example.com/gateway` 与 `https://openclaw.example.com`，再使用：

```bash
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=wss://openclaw.example.com/gateway
HORIZON_OPENCLAW_IMAGE_IO_ENABLED=true
HORIZON_OPENCLAW_MEDIA_ORIGINS=https://openclaw.example.com
```

同时必须把 `https://openclaw.example.com` 精确加入本文件 Nginx CSP 的 `img-src`
（禁止 `*`），并把 Inteliscope 的精确站点 Origin 加入 Gateway
`gateway.controlUi.allowedOrigins`。负载均衡器要透传 WebSocket Upgrade 与媒体 GET；
Gateway 多副本必须共享会话/媒体索引、持久化媒体存储及票据签名密钥。签名密钥应由
SecretStore 或环境引用提供；Gateway 使用 `OPENCLAW_MANAGED_MEDIA_TICKET_KEYS`，格式为
`当前kid:base64url密钥,上一kid:base64url密钥`（每把至少 32 bytes，当前在前，最多两把），
不要把实际值写入仓库或普通配置。轮换时至少同时接受当前和上一把密钥一个票据 TTL；对象
存储不得直接暴露给浏览器，仍由 Gateway 在鉴权后代理。媒体响应应为 private/no-store
并返回 `X-Content-Type-Options: nosniff`。发布顺序是先固定 Gateway、配置共享存储和
密钥、发布但关闭 Inteliscope 开关、完成真实 Canary 后再开启。
