# VPS RSSHub（本地与 VPS 共用）

只在 `vps-tokyo` 运行一套 RSSHub。容器加入生产
`infohub-light_default` 网络，并把宿主机 `1200` 仅绑定到 loopback；现有
Nginx 通过 HTTPS `/rsshub/` 前缀提供带 RSSHub 原生访问控制的测试入口：

- VPS Inteliscope：RSSHub Base URL 使用 `http://rsshub:1200`
- 本地 Inteliscope：RSSHub Base URL 使用 `https://rb.jiefs.top/rsshub`
- 第三方实例：直接把同一设置改为其 HTTP(S) Base URL；来源记录无需迁移

本地不运行第二套 RSSHub，也不使用 SSH tunnel。

## 访问密钥

自建实例必须在两端 `data/secrets.env` 中设置同一个
`RSSHUB_ACCESS_KEY`。配置 JSON、catalog、MCP、OpenClaw 和 Feed 都不保存或
返回该值。Worker 请求时只发送按 RSSHub 规则从“route path + master key”
计算的 route-scoped `code`，不会把主密钥放进公网 URL。

使用 `SecretStore` 写入该变量：

```bash
./.venv/bin/python -c \
  "from src.services.secret_store import SecretStore; SecretStore('data').set('RSSHUB_ACCESS_KEY', 'replace-with-a-random-secret')"
```

示例值不得提交到仓库。部署时 Compose 显式读取 SecretStore 文件：

```bash
docker compose \
  --env-file data/secrets.env \
  -f deploy/rsshub-vps.compose.yml \
  pull
docker compose \
  --env-file data/secrets.env \
  -f deploy/rsshub-vps.compose.yml \
  up -d
```

## Nginx HTTPS 入口

把 `deploy/nginx-rsshub-location.conf` 放入 VPS Nginx snippets，并只在
`rb.jiefs.top` 的 HTTPS `server` 中 include。先运行 `nginx -t`，通过后再
reload。HTTP server 继续统一跳转 HTTPS。

未鉴权的公网探针必须被 RSSHub 拒绝：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://rb.jiefs.top/rsshub/healthz
```

正常抓取由 Inteliscope Worker 使用 route code 完成。Nginx 对该 location
关闭 access log，避免 route code 进入常规访问日志；容器的 `1200` 不直接
暴露公网。

## 既有来源迁移

先停止对应环境的 Worker，再 dry-run 和 apply。脚本只识别精确的
`/bilibili/user/video/<uid>[/1]` URL，保留 source、subscription 与 schedule
ID，并在写入前备份 `config.json` 和 SQLite：

```bash
./.venv/bin/python scripts/migrate_rsshub_sources.py \
  --data-dir data \
  --base-url https://rb.jiefs.top/rsshub

./.venv/bin/python scripts/migrate_rsshub_sources.py \
  --data-dir data \
  --base-url https://rb.jiefs.top/rsshub \
  --apply
```

VPS 的 `--base-url` 使用 `http://rsshub:1200`。迁移后的来源只保存
`site=bilibili`、`route_key=user_video` 与 `params.uid`；运行时再拼接当前
Base URL，所以从自建实例切到第三方实例不改变订阅身份。
