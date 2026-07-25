# Remote MCP 只读 API-only 发布运行手册

本手册只发布现有 `horizon-api` 中的 Remote MCP。生产固定关闭订阅写入，
不得启动 `horizon-worker`、legacy scheduler、抓取、AI 或付费来源。

## 1. 固定边界与准备

发布必须来自干净、已授权的 commit。`scripts/release_rc1.sh prepare` 是首次
建库流程，已有生产 `service.db` 时不得复用。记录当前 release、镜像、API
容器、数据库大小和 API RSS，然后只运行一次 release gate：

```bash
git status --short
git rev-parse HEAD
./.venv/bin/python scripts/test_gate.py run --mode release
```

生成不可变标识并归档当前 commit：

```bash
RELEASE_ID="mcp-read-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short=12 HEAD)"
IMAGE="inteliscope-service:${RELEASE_ID}"
ARCHIVE="$(mktemp -t inteliscope-mcp-read.XXXXXX.tar.gz)"
git archive --format=tar.gz --output="$ARCHIVE" HEAD
scp "$ARCHIVE" vps-tokyo:/tmp/"${RELEASE_ID}".tar.gz
```

在服务器解包并构建镜像。release 目录只包含代码，生产数据继续位于
`/opt/inteliscope/data`：

```bash
ssh vps-tokyo
set -euo pipefail
BASE=/opt/inteliscope
RELEASE_ID=上一步生成的值
IMAGE="inteliscope-service:${RELEASE_ID}"
RELEASE_DIR="$BASE/releases/$RELEASE_ID"
mkdir -p "$RELEASE_DIR"
tar -xzf "/tmp/${RELEASE_ID}.tar.gz" -C "$RELEASE_DIR"
docker build --pull -t "$IMAGE" "$RELEASE_DIR"
```

## 2. 生产快照脱敏 staging

staging 必须使用服务器内生产快照，不得挂载生产数据库。现有 sanitizer 使用
SQLite backup 复制数据库，并只在副本中清空 sessions、delegations、schema v7
proposals、heartbeat 和 active job claim：

```bash
STAGING_ROOT="$BASE/staging/$RELEASE_ID"
mkdir -p "$STAGING_ROOT/data" "$STAGING_ROOT/logs"
python3 "$RELEASE_DIR/scripts/prepare_service_deployment.py" \
  --source "$BASE/data/service.db" \
  --output "$STAGING_ROOT/data/service.db"
python3 - "$STAGING_ROOT/data/service.db" <<'PY'
import os, sys
assert os.stat(sys.argv[1]).st_mode & 0o777 == 0o600
PY
```

启动唯一的 staging API 容器。它使用独立数据目录、独立容器名和
`127.0.0.1:18080`，不使用 Compose 的固定生产容器名：

```bash
docker rm -f horizon-mcp-staging 2>/dev/null || true
docker run -d --name horizon-mcp-staging \
  -p 127.0.0.1:18080:8080 \
  -v "$STAGING_ROOT/data:/app/data" \
  -v "$STAGING_ROOT/logs:/app/logs" \
  -v "$BASE/.env:/app/.env:ro" \
  -e HORIZON_REMOTE_MCP_ENABLED=true \
  -e HORIZON_REMOTE_MCP_PUBLIC_URL=http://127.0.0.1:18080/mcp \
  -e HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false \
  -e HORIZON_REQUIRE_WORKER_FOR_READINESS=false \
  -e HORIZON_SQLITE_JOURNAL_MODE=DELETE \
  --entrypoint uv "$IMAGE" \
  run --no-sync horizon-api --host 0.0.0.0 --port 8080
curl -fsS http://127.0.0.1:18080/api/health/ready
```

本机建立 tunnel，在 staging Web 中使用两个不同用户分别创建 read connection：

```bash
ssh -N -L 18080:127.0.0.1:18080 vps-tokyo
```

令牌只写本机权限为 `0600` 的环境文件或用隐藏输入读入当前 shell；不得放进
聊天、命令参数、URL 或日志：

```bash
read -rsp 'Primary MCP token: ' INTELISCOPE_MCP_TOKEN; echo
read -rsp 'Secondary MCP token: ' INTELISCOPE_MCP_SECONDARY_TOKEN; echo
export INTELISCOPE_MCP_TOKEN INTELISCOPE_MCP_SECONDARY_TOKEN
export INTELISCOPE_MCP_URL=http://127.0.0.1:18080/mcp
./.venv/bin/python scripts/remote_mcp_read_canary.py verify
openclaw mcp doctor inteliscope --probe
openclaw mcp status --verbose
```

验收输出必须是 16 个服务端工具、12 个安全 read tools、3 个隔离检查和
`subscription_writes_disabled`。再用真实 OpenClaw 对话询问“哪些订阅来源最近
异常？”、“最近有哪些任务失败，原因是什么？”和“查看该任务最近 24 小时的
安全诊断事件”，并要求“订阅 B 站 UP 主食贫道”；最后一项必须自行解析唯一
精确名称 UID 并只生成订阅预览，不得要求手工提供 UID，也不得在未确认时
apply。事件结果不得包含原始日志、路径或身份。

## 3. Nginx 精确路由

只把 `deploy/nginx/inteliscope-rate-limit.conf` 的 MCP zone 加入 `http` context，
并把 `location = /mcp` 最小合入当前线上
`/etc/nginx/sites-enabled/cfl.conf` 的 `rb.jiefs.top cfl.rb.jiefs.top` server。
不得整份覆盖当前 Nginx server block，也不得改变 `/cfl`、现有域名或其他
location。修改前保留带 release ID 的原文件备份。

必须保留以下边界：`auth_basic off`、`client_max_body_size 256k`、每 IP
120 req/min、burst 10、8 个并发连接、`Authorization` 原样透传、
`proxy_buffering off`。先安装限流区、备份并编辑站点，只做配置校验：

```bash
sudo cp deploy/nginx/inteliscope-rate-limit.conf \
  /etc/nginx/conf.d/inteliscope-rate-limit.conf
sudo cp -a /etc/nginx/sites-enabled/cfl.conf \
  "/etc/nginx/sites-enabled/cfl.conf.${RELEASE_ID}.bak"
# 只向现有 443 server 增加 deploy 模板中的精确 location = /mcp。
sudo nginx -t
```

此时不要 reload：旧 API 不具备 Remote MCP 的精确 fallback。新 API 健康后再
reload，确保公网 `/mcp` 从未落入旧 SPA HTML。

## 4. 生产 API-only 切换

记录旧镜像和 release。在 active jobs 为 0 时同时停止 API 与 Worker，再创建
`0600` 备份；正常回滚保留 additive schema v7，不恢复旧 schema：

```bash
PREVIOUS_IMAGE="$(docker inspect horizon-light-api --format '{{.Config.Image}}')"
PREVIOUS_RELEASE="$(readlink "$BASE/current" || true)"
docker stop horizon-light-api horizon-light-worker
! docker ps --format '{{.Names}}' | grep -E \
  'horizon-light-(api|worker|scheduler)'
BACKUP="$BASE/backups/mcp-read-${RELEASE_ID}"
mkdir -p "$BACKUP"
install -m 600 "$BASE/data/service.db" "$BACKUP/service.db"
python3 - "$BACKUP/service.db" <<'PY'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert db.execute("PRAGMA foreign_key_check").fetchall() == []
PY
```

原子更新共享 `.env` 中以下值，不改其他秘密或运行配置：

```text
INTELISCOPE_IMAGE=<本次不可变镜像>
HORIZON_WEB_BIND=127.0.0.1
HORIZON_WEB_PORT=8080
HORIZON_REMOTE_MCP_ENABLED=true
HORIZON_REMOTE_MCP_PUBLIC_URL=https://rb.jiefs.top/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_REQUIRE_WORKER_FOR_READINESS=false
HORIZON_AUTH_SECURE_COOKIE=true
```

为 release 链接持久化目录，然后只启动 `horizon-api`：

```bash
rm -rf "$RELEASE_DIR/data" "$RELEASE_DIR/logs" "$RELEASE_DIR/.env"
ln -s "$BASE/data" "$RELEASE_DIR/data"
ln -s "$BASE/logs" "$RELEASE_DIR/logs"
ln -s "$BASE/.env" "$RELEASE_DIR/.env"
docker rm horizon-light-api
cd "$RELEASE_DIR"
docker compose -f docker-compose.light.yml up -d --no-build --force-recreate horizon-api
curl -fsS http://127.0.0.1:8080/api/health/live
curl -fsS http://127.0.0.1:8080/api/health/ready
! docker ps --format '{{.Names}}' | grep -E 'horizon-light-worker|horizon-light-scheduler'
sudo nginx -t
sudo systemctl reload nginx
ln -sfn "$RELEASE_DIR" "$BASE/current"
```

确认生产数据库 integrity、foreign keys、schema v6/v7 marker 和 proposal 数量，
然后在生产 Web 用两个真实用户创建 read connection，重新执行：

```bash
export INTELISCOPE_MCP_URL=https://rb.jiefs.top/mcp
./.venv/bin/python scripts/remote_mcp_read_canary.py verify
```

在 Web 吊销 primary connection，保留当前 shell 中的旧 token，只验证一次：

```bash
./.venv/bin/python scripts/remote_mcp_read_canary.py expect-unauthorized
```

必须返回 HTTP 401。检查 proposal 数量与 canary 前一致，然后清除 shell 变量。

## 5. 24 小时观察

观察 24 小时并记录：MCP 5xx/`internal_error`/意外 429 为 0；热身后
closed-world 读调用 p95 小于 2 秒，单次 Bilibili 名称查询小于其 8 秒 I/O
timeout；API RSS 相对启用前没有超过 80 MiB 的持续增长；proposal 数量
不因只读调用增长；`last_used_at` 有界更新；Worker、scheduler、抓取、AI 和
付费调用均为 0。观察期只通知 canary 用户，不增加服务器 allowlist。

## 6. 回滚与清理

先将 `HORIZON_REMOTE_MCP_ENABLED=false`，保持写 flag 为 false，只重建
`horizon-api`。若新代码异常，再把 `INTELISCOPE_IMAGE` 和 `$BASE/current`
恢复为记录的旧值并启动旧 API；正常回滚保留 additive schema v6/v7，不执行
降级迁移。应用确认关闭后再移除 Nginx 精确 `/mcp` location。

只有数据库损坏且获得单独授权时才停服恢复备份。最后删除 staging token、
容器和脱敏副本：

```bash
docker rm -f horizon-mcp-staging 2>/dev/null || true
rm -rf "$STAGING_ROOT"
unset INTELISCOPE_MCP_TOKEN INTELISCOPE_MCP_SECONDARY_TOKEN INTELISCOPE_MCP_URL
```
