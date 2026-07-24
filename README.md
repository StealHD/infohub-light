# Inteliscope

Inteliscope is a small-group, multi-user information feed built from Horizon. Its current product surface is deliberately narrow: subscribe to sources, acquire new items, read a user-scoped Feed, and retain Feed history.

[简体中文](README_zh.md) · [API contract](API_CONTRACT.md) · [Architecture](ARCHITECTURE_CONTRACT.md)

## Current product

- Per-user accounts and `owner/admin/member/viewer` roles.
- Public, workspace, and private source subscriptions.
- RSS/Atom, GitHub releases/users, Reddit subreddits/users, Telegram channels, Apify social targets, and Hacker News.
- Manual, per-user scheduled Feed refresh, and per-subscription scheduled source fetch through the same SQLite-backed Worker queue.
- User-scoped Feed snapshots, stable saved/later content, explicit read/unread state, captured-body detail, protected media, history, and source health.
- Editable source and subscription settings, connection tests, refetch, partial/failure diagnostics, and source priority ordering.
- Bounded per-item summaries and owner/admin write-only management of AI and Apify keys.
- Optional read-only Remote MCP for each user's own local OpenClaw, with self-managed 90-day connections and a bundled Skill.

Graph, archive analytics, recommendation learning, in-site article proxying, daily summary publishing, and notifications are not part of the default Service product. The legacy CLI and scheduler remain optional compatibility paths only.

## Default runtime

The default deployment contains exactly two services:

```text
horizon-api     FastAPI, React reader UI, authentication and Service APIs
horizon-worker  acquisition jobs, Feed finalization, schedules and source health
```

`horizon-scheduler` is never started by default and does not participate in the multi-user Feed path.

## Local Docker start

```bash
cp .env.example .env

# For a fresh database, configure an initial owner with either a password
# or a PBKDF2 password hash before the first start.
# HORIZON_AUTH_USER=admin
# HORIZON_AUTH_PASSWORD_HASH=...

./scripts/up-latest.sh
docker compose -f docker-compose.light.yml ps
curl http://127.0.0.1:8080/api/health/live
curl http://127.0.0.1:8080/api/health/ready
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/), log in, create or subscribe to a source, and select “获取新内容”.

Runtime data is mounted from `./data` and `./logs`. Production images do not contain `.env`, `service.db`, `data/config.json`, logs, or backups.
API, Worker, Scheduler, and CLI runtime/operation logs are private UTC-rotated JSONL files with a 30-day default retention. See the [diagnostic logging developer guide](docs/dev/observability-logging.md); logs are never rendered in the frontend.

The default Service UI is the React three-column radar. For frontend development:

```bash
cd frontend
npm ci
npm run dev       # Vite on 127.0.0.1:5173, /api proxied to FastAPI :8080
npm test
npm run typecheck
npm run e2e
```

Set `HORIZON_SERVICE_UI_VARIANT=legacy` for the one-release rollback path. This does not change the legacy CLI/static publisher boundary.

Owner/admin users can add and rotate AI/Apify keys in the configuration page. Values are write-only, stored in ignored `data/secrets.env` with mode `0600`, hot-loaded by API and Worker, and never returned to the browser. `data/config.json` and SQLite contain only the selected environment-variable reference.

## Authentication

The Service API always requires an application account. `HORIZON_AUTH_ENABLED` controls only the legacy Web profile and cannot disable Service authentication.

For HTTPS deployments:

```bash
HORIZON_AUTH_SECURE_COOKIE=true
HORIZON_AUTH_SESSION_TTL_SECONDS=604800
```

Nginx Basic Auth may be used as an additional outer gate, but it never replaces the application account and role checks.

## Local OpenClaw assistant

Remote MCP is disabled by default and does not run an Agent or model on the server. When enabled, every role can create a connection from `/agents`; the clear-text token is shown once. A read connection exposes eleven safe Feed, subscription, source guidance, health, job, diagnosis, and sanitized operation-event tools for that user. Subscription changes require a separately authorized connection and server flag.

Browser chat is a separate opt-in connection. The browser connects directly to the user's OpenClaw Gateway v4; Inteliscope never proxies the Gateway or stores its bootstrap token. Local development accepts only `ws://127.0.0.1` or `ws://localhost`, while a remote per-user Gateway must use `wss://`. Paired browser credentials are isolated by Inteliscope user and Gateway URL. Turning the chat flag off restores the copy-only handoff without affecting Remote MCP.

For local development:

```bash
HORIZON_REMOTE_MCP_ENABLED=true
HORIZON_REMOTE_MCP_PUBLIC_URL=http://127.0.0.1:8080/mcp
HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false
HORIZON_OPENCLAW_CHAT_ENABLED=false
HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:18789
```

For first-time local integration, use the idempotent bootstrap. It discovers the
actual Gateway URL, merges the current browser Origin, updates `.env`, installs
the bundled Skill, starts the services, and verifies readiness. It never reads
or stores Gateway/MCP tokens and never approves a device:

```bash
./scripts/setup_openclaw_local.sh --dry-run
./scripts/setup_openclaw_local.sh
```

The default reuses the current Docker image; pass `--rebuild` to rebuild the
working tree. Afterward, create a read-only connection on `/agents`, run its
generated MCP commands, then pair the Feed panel with `openclaw dashboard`.

Install and configure the bundled Skill by following [`integrations/openclaw/inteliscope/README.md`](integrations/openclaw/inteliscope/README.md). The legacy stdio MCP remains separate and is never exposed by `/mcp`.

The local acceptance benchmark uses an isolated temporary database and 100 real MCP client calls:

```bash
./.venv/bin/python scripts/benchmark_remote_mcp.py
```

## `rb.jiefs.top` RC deployment

Public deployment is currently paused while the local acquisition loop is being completed. The commands below remain the guarded release path and must not be run without renewed authorization.

The repository includes a guarded two-phase deployment flow for `vps-tokyo`:

```bash
# Create a sanitized deployment copy. This does not mutate data/service.db.
./.venv/bin/python scripts/prepare_service_deployment.py \
  --source data/service.db \
  --output /tmp/inteliscope-service-rc1.db

# Requires a clean, authorized release commit. Runs all local gates, creates
# a git archive, builds on the VPS and starts API-only staging on port 18080.
./scripts/release_rc1.sh prepare /tmp/inteliscope-service-rc1.db

# After staging validation, switch 8080 and start API + Worker.
./scripts/release_rc1.sh promote <release-id>

./scripts/release_rc1.sh status
./scripts/release_rc1.sh rollback <release-id>
```

The public target is `https://rb.jiefs.top/`. VPS releases live under `/opt/inteliscope/releases/<release-id>` and share `/opt/inteliscope/{data,logs,.env}`.

## Verification

```bash
./.venv/bin/pytest -q
node --test tests/reading_ui_behavior.test.cjs tests/subscription_job_ui_behavior.test.cjs
for file in src/ui/static/*.js; do node --check "$file"; done
./.venv/bin/python -m compileall -q src scripts
docker compose -f docker-compose.light.yml config
git diff --check
```

## Legacy compatibility

The upstream-style `horizon` CLI, static site output, summaries, notifications, and scheduler remain available through explicit manual/profile commands. They may write global files under `data/site/`, but the Service API, Worker, Feed, and history must never use those files as a fallback.

Inteliscope is derived from [Thysrael/Horizon](https://github.com/Thysrael/Horizon) and remains MIT licensed.
