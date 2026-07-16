# Service API Smoke Checklist

本检查只验证小团体核心 `/api/*` 是否可登录、可读取、可创建 queued job、可做最小成员管理。脚本本身不访问真实外网源、不启动服务、不做归档分析扩展；默认 compose 运行单元是 API + Worker。

## 脚本方式

启动 API 后运行：

```bash
./.venv/bin/python scripts/service_api_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --json-output logs/service-api-smoke-latest.json
```

需要验证写路径时增加 `--mutating`：

```bash
./.venv/bin/python scripts/service_api_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --mutating \
  --json-output logs/service-api-smoke-latest.json
```

`--mutating` 会创建或复用一个 `member-ui-smoke` 成员并 PATCH 启用状态/角色，创建或复用一个 private RSS smoke source、订阅它、创建 `source_test` queued job；如果当前 feed 有 item，会验证 item state 和 compatibility-only feedback API。后者不是默认 UI 能力。报告不得包含密码或 `password_hash`。

## 静态 UI smoke

启动 API 后运行：

```bash
./.venv/bin/python scripts/service_ui_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --json-output logs/service-ui-smoke-latest.json
```

UI smoke 会登录 API、读取 `/` 和静态 JS/CSS 资源、确认页面包含阅读/订阅/配置入口，并检查静态 JS 不再请求本地 `radar-data.json`、`history-data.json` 或 `article-graph.json`。需要验证 UI 写路径时可增加 `--mutating`，它只创建本地 smoke private RSS source 和 queued `source_test` job，不访问外网。

## Docker 组合验收

默认启动 Docker API + Worker，并验证 readiness 和无外网依赖的核心 API smoke；scheduler 不启动：

```bash
./.venv/bin/python scripts/service_stack_smoke.py \
  --compose-file docker-compose.light.yml \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --api-only \
  --json-output logs/service-stack-smoke-latest.json
```

需要同时跑静态 UI smoke 时增加 `--include-ui-smoke`：

```bash
./.venv/bin/python scripts/service_stack_smoke.py \
  --compose-file docker-compose.light.yml \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --api-only \
  --include-ui-smoke \
  --json-output logs/service-stack-smoke-latest.json
```

需要跑真实公共源闭环时显式开启 full 模式：

```bash
./.venv/bin/python scripts/service_stack_smoke.py \
  --compose-file docker-compose.light.yml \
  --base-url http://127.0.0.1:8080 \
  --username "$HORIZON_AUTH_USER" \
  --password "$HORIZON_AUTH_PASSWORD" \
  --full-real-source \
  --run-worker \
  --json-output logs/service-stack-smoke-latest.json
```

组合报告只汇总 `compose_up`、`api_health`、`api_smoke`、`ui_smoke`、`real_source_smoke` 等步骤状态和子报告路径；核心 API、UI 和真实源 smoke 仍各自写入独立 JSON 报告。默认 `--api-only` 不访问外网，不启动 scheduler，不触发通知或 webhook。

## 浏览器手动验收

Docker API 启动后打开 `http://127.0.0.1:8080/`：

1. 未登录时应显示登录门禁，阅读、订阅写操作不可用。
2. 登录后阅读页应能加载 `/api/feed/latest` 的空状态或 item。
3. 订阅页应显示公共源市场、我的订阅、任务队列和 API 状态。
4. viewer 角色写按钮应禁用，并显示“viewer 只读，不能执行写操作”。
5. 阅读页 item 的标记已读、收藏、稍后读和忽略按钮应有可见反馈；选中条目不得自动标记已读，已读按钮不得再次取消，浏览器 console 不应出现明显 API 路径错误。
6. 订阅页顶部应显示默认关闭的“自动更新信息流”卡片和 1/3/6/12/24 小时选项；viewer 控件禁用，member 启用前没有有效订阅时显示 `no_enabled_subscriptions`。
7. 创建本地/测试 RSS 后点击首页“获取新内容”或订阅页“立即刷新”，应看到按钮立即禁用、重复提交复用同一 job、任务从 queued/running 到 succeeded 或 partial，随后自动加载新 Feed；Worker missing/stale 时应显示明确排队提示。

## Feed v2 迁移检查

只读检查，不修改数据库：

```bash
./.venv/bin/python scripts/migrate_user_feed_v2.py \
  --data-dir data \
  --backup-dir data/backups
```

真实迁移必须先停止 API、Worker 和 scheduler，再显式增加 `--apply`。脚本先生成权限为 `0600` 的 UTC 时间戳备份；已迁移数据库重复执行会返回 `already_migrated`，不会再次清空数据。

## curl 最小流程

登录并保存 cookie：

```bash
curl -sS -c /tmp/infohub-cookie.txt \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$HORIZON_AUTH_USER\",\"password\":\"$HORIZON_AUTH_PASSWORD\"}" \
  http://127.0.0.1:8080/api/auth/login
```

读取核心状态：

```bash
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/auth/status
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/config
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/dashboard/summary
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/users
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/catalog/sources
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/feed/latest
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/me/feed-schedule
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/jobs
```

管理员重置成员密码时，只在请求体传入一次 `password`；响应不得返回 `password_hash`：

```bash
curl -sS -b /tmp/infohub-cookie.txt \
  -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"role":"member","enabled":true,"display_name":"Member","password":"new-password"}' \
  http://127.0.0.1:8080/api/users/<user_id>
```

创建 private RSS smoke source：

```bash
curl -sS -b /tmp/infohub-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "scope": "private",
    "type": "rss",
    "display_name": "Smoke - Service API Private RSS",
    "default_channel": "AI",
    "default_topics": ["Smoke"],
    "config": {
      "name": "Smoke - Service API Private RSS",
      "url": "https://example.com/infohub-service-smoke.xml"
    }
  }' \
  http://127.0.0.1:8080/api/catalog/sources
```

订阅并创建测试 job：

```bash
SOURCE_ID="src_xxx"

curl -sS -b /tmp/infohub-cookie.txt \
  -X POST \
  http://127.0.0.1:8080/api/catalog/sources/$SOURCE_ID/subscribe

curl -sS -b /tmp/infohub-cookie.txt \
  -H 'Content-Type: application/json' \
  -d "{\"source_id\":\"$SOURCE_ID\",\"payload\":{}}" \
  http://127.0.0.1:8080/api/jobs/source-test
```

验证显式 item state：

```bash
ARTICLE_ID="rss:item:example"

curl -sS -b /tmp/infohub-cookie.txt \
  "http://127.0.0.1:8080/api/me/item-state?article_ids=$ARTICLE_ID"

curl -sS -b /tmp/infohub-cookie.txt \
  -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"is_read":true,"is_saved":true}' \
  "http://127.0.0.1:8080/api/me/items/$ARTICLE_ID/state"
```

所有失败响应都应为：

```json
{"ok": false, "error": {"code": "...", "message": "...", "retryable": false, "action": "..."}}
```
