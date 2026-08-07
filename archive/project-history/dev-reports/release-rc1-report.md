# Inteliscope `rb.jiefs.top` RC1 发布报告

## 状态

`deployed_api_only_worker_disabled`：用户已明确授权部署当前工作区版本，但要求不启动 Worker。2026-07-14 已完成 18080 staging、8080 promote 和旧版清理；当前仅运行健康的 API，Worker 与 scheduler 均不存在。

## 目标

- VPS：`vps-tokyo`
- 公网：`https://rb.jiefs.top/`
- 当前目录：`/opt/inteliscope/releases/api-20260714T110652Z-d0c8905-wt2e4cb2ea`，`/opt/inteliscope/current` 指向该目录
- 当前容器：仅 `horizon-light-api`
- `horizon-worker` 与 legacy `horizon-scheduler`：按用户要求不启动，且无 systemd/cron 自动拉起项
- 公网认证：仅保留应用 `admin`/owner 登录；Nginx Basic Auth 已移除

## 已完成的本地证据

- 跨用户异步 UI 修复：订阅 Node 行为测试 45/45；全部 Node DOM 54/54。
- 完整 pytest：627 项收集，全部通过；全部 Node DOM 54/54。
- Service login 使用环境 TTL 与 Secure Cookie 设置。
- liveness 返回 `version/revision/built_at`。
- Dockerfile 不复制运行 `data/`，`.dockerignore` 排除数据库、配置、日志和备份。
- API 与 Worker 使用同一个 `INTELISCOPE_IMAGE`。
- `prepare_service_deployment.py` 通过测试：SQLite backup 副本清除 session、heartbeat、active job，并验证 Feed v2、integrity、foreign keys 和 `0600`。
- `release_rc1.sh` 具备 clean-tree、完整本地 gate、`git archive`、18080 staging、8080 promote、rollback 和 status 流程。
- Python compileall、全部 JS `node --check`、两份 Compose config、shell `bash -n`、JSON defaults 和 `git diff --check` 均通过。
- 真实 Docker build context 为 15.84 KB；审查中发现“只排除部分 data 文件”仍会把其他 data 发送给 builder，已改为排除整个 `data/` 并新增 RED/GREEN 测试。
- 本机 API 与 Worker 使用同一 image ID，均 healthy、restart count 0；镜像内 `/app/data`、`/app/logs` 为空，无 `.env`、tests、service.db 或 config.json。
- 本机浏览器显示 24 条 Feed、4/4 来源 healthy、6 小时自动计划和 Worker ready；已删除 Graph/站内预览/偏好反馈入口，订阅编辑/测试/重新抓取存在，console error/warn 为 0。
- init-pro validator 已升级为 schema 3，而仓库控制面仍为 schema 2；旧文档命令不再被当前工具接受。本期未擅自迁移控制面，project-defaults 本身已通过 JSON 解析。

## VPS 发布证据

- Node 22/npm 10 首次构建暴露旧 lockfile 缺少 Linux optional peer 项；使用 npm 10 重新生成并在全新目录验证 `npm ci` 后，容器构建成功，355 个包审计 0 漏洞。
- 18080 staging：live/ready/root 均为 200，版本 `1.5.0`、revision `d0c8905-wt-2e4cb2ea`，restart count 0。
- 8080 production：API healthy，ready 返回 database ready 与 `worker_status=missing`；`HORIZON_REQUIRE_WORKER_FOR_READINESS=false`，共享获取和 compact snapshot writer 均为 false。
- 数据库：integrity `ok`、foreign-key error 0、session/heartbeat/active job 均为 0；数据库与 `.env` 权限均为 `0600`。
- 公网 HTTPS 证书校验通过；Nginx Basic Auth 已移除，根页面无需浏览器弹窗返回 200，受保护 API 未登录仍由应用返回 401；随机强密码重置后，`admin`/owner 公网登录和注销已通过。
- 旧 `horizon-web`/scheduler 容器、3 个旧镜像、旧网络、旧源码和失败发布残留已删除；压缩回滚备份保留并通过 gzip 校验。

## 后续门槛

1. 公网应用登录、owner 角色与 Secure Cookie 已验证；Feed、订阅、历史和页面级人工验收仍待完成。
2. Feed storage v3 仍需停服务、备份、显式 apply 和 integrity/foreign-key 验收，之后才可考虑 compact writer。
3. Worker 与 scheduler 继续禁用；启动 Worker、自然周期或付费来源都需要新的明确授权。

## 发布字段

- release id：`api-20260714T110652Z-d0c8905-wt2e4cb2ea`
- source identity：HEAD `d0c8905` + 工作区归档 SHA-256 `2e4cb2eae92d6156e44067d9afa263c0ba3ae109c760b8c004037eed34dc5bd4`；本次未创建 commit/tag
- built at：`2026-07-14T11:06:52Z`
- image digest：`sha256:2b4b9ddd162db0965c5b288fb7bffe7437c1a29c6253bef1c9e35f638f1599cb`
- database artifact：`/opt/inteliscope/data/service.db`，sanitized、mode `0600`
- staging result：18080 live/ready/root 通过
- production result：8080 API healthy、restart count 0，仅 API 运行
- rollback backup：`/opt/inteliscope/backups/api-20260714T110039Z-d0c8905-wta3782641/legacy-deployment.tar.gz`，SHA-256 `20bde0568c963dec5bab3acd642bfe63f5efd7cd11ec7afb1f97ee055791922c`
- auth change backups：`/opt/inteliscope/backups/nginx-basic-auth-removal-20260714T115024Z/` 与 `/opt/inteliscope/backups/password-reset-random-20260714T115110Z/`
