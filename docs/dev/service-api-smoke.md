# Service API Smoke Checklist

本检查只验证小团体核心 `/api/*` 是否可登录、可读取、可创建 queued job。它不访问真实外网源，不启动 Worker，不做归档分析扩展。

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

`--mutating` 会创建或复用一个 private RSS smoke source、订阅它、创建 `source_test` queued job；如果当前 feed 有 item，会验证 item state 和 feedback API。

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
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/catalog/sources
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/feed/latest
curl -sS -b /tmp/infohub-cookie.txt http://127.0.0.1:8080/api/jobs
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

验证 item state 和 feedback：

```bash
ARTICLE_ID="rss:item:example"

curl -sS -b /tmp/infohub-cookie.txt \
  "http://127.0.0.1:8080/api/me/item-state?article_ids=$ARTICLE_ID"

curl -sS -b /tmp/infohub-cookie.txt \
  -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"is_read":true,"is_saved":true}' \
  "http://127.0.0.1:8080/api/me/items/$ARTICLE_ID/state"

curl -sS -b /tmp/infohub-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"feedback_type":"not_relevant","metadata":{"surface":"curl"}}' \
  "http://127.0.0.1:8080/api/me/items/$ARTICLE_ID/feedback"
```

所有失败响应都应为：

```json
{"ok": false, "error": {"code": "...", "message": "...", "retryable": false, "action": "..."}}
```
