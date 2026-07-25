# VPS RSSHub（本地与 VPS 共用）

只在 `vps-tokyo` 运行一套 RSSHub。容器加入生产
`infohub-light_default` 网络，同时把 `1200` 仅绑定到 VPS loopback：

- VPS Inteliscope：Settings → RSSHub Base URL 使用 `http://rsshub:1200`
- 本地 Docker Inteliscope：通过 SSH tunnel 访问，Base URL 使用
  `http://host.docker.internal:1200`
- 第三方实例：直接把同一设置改为其 HTTP(S) origin；来源记录不需要迁移

## VPS 启动

```bash
docker compose -f deploy/rsshub-vps.compose.yml pull
docker compose -f deploy/rsshub-vps.compose.yml up -d
docker compose -f deploy/rsshub-vps.compose.yml ps
curl --fail http://127.0.0.1:1200/healthz
```

不得把 Compose 中的 host bind 改成 `0.0.0.0`。RSSHub 不经过公网 Nginx，
也不配置 Bilibili Cookie 或 ACCESS_KEY。

## macOS 私有通道

本地 `1200` 转发到 VPS loopback：

```bash
ssh -NT \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:1200:127.0.0.1:1200 \
  vps-tokyo
```

宿主机可用 `curl --fail http://127.0.0.1:1200/healthz` 验证；Docker Desktop
容器使用 `http://host.docker.internal:1200`。生产部署不依赖该 tunnel。

## 既有来源迁移

先停止对应环境的 Worker，再 dry-run 和 apply。脚本只识别精确的
`/bilibili/user/video/<uid>[/1]` URL，保留 source、subscription 与 schedule
ID，并在写入前备份 `config.json` 和 SQLite：

```bash
./.venv/bin/python scripts/migrate_rsshub_sources.py \
  --data-dir data \
  --base-url http://host.docker.internal:1200

./.venv/bin/python scripts/migrate_rsshub_sources.py \
  --data-dir data \
  --base-url http://host.docker.internal:1200 \
  --apply
```

VPS 的 `--base-url` 改为 `http://rsshub:1200`。迁移后的来源只保存
`site=bilibili`、`route_key=user_video` 与 `params.uid`；运行时再拼接当前
Base URL，所以从自建实例切到第三方实例不改变订阅身份。
