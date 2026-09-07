# OpenClaw 服务端连接

在生产 `.env` 配置：

```dotenv
HORIZON_OPENCLAW_CHAT_ENABLED=true
HORIZON_OPENCLAW_SERVER_ENABLED=true
HORIZON_OPENCLAW_SERVER_URL=wss://www.senjee.top:4430
HORIZON_OPENCLAW_SERVER_TOKEN=<通过安全通道写入当前 Gateway Token>
```

Token 不写入 Git，不从浏览器下发。API 上线前将部署用设备私钥放入 `data/openclaw-relay/device.key`（目录0700、文件0600），并在 Gateway 批准这一个设备的 operator.read/operator.write。不可批准未知设备或关闭鉴权。

此模式仅供 owner/admin 使用。API 的 `/api/me/openclaw/socket` 需由同源 Nginx 转发 WebSocket Upgrade/Connection，read timeout 至少60秒；公网不需要增加浏览器到 Gateway 的 IP 白名单。Gateway 白名单只放行 API 服务器出口。

浏览器刷新后会显示服务端连接说明；以前保存的直连地址不会覆盖服务端模式。会话恢复索引只存在当前用户 sessionStorage；Gateway 凭据不在浏览器保存。不同用户的会话由独立归属表强制隔离。当前模式提供普通对话、历史恢复和模型选择；尚未开放工作区管理、自动化、产物和全局会话目录 RPC。上线验证应覆盖匿名/Origin/角色拒绝、跨账号会话拒绝、Cookie过期断开、模型列表、无外发 chat.send、API/Worker readiness。

回滚：保留归属数据和私钥，设置 `HORIZON_OPENCLAW_SERVER_ENABLED=false` 并恢复上一镜像；兼容模式重新使用 `HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL`。不要删除原有 Service 数据。HTTPS证书手动DNS续期不由本功能接管。
