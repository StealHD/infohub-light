# Inteliscope 使用说明

这份说明面向日常使用和小范围分享。当前部署入口为：

- 公网入口：`https://rb.jiefs.top/`
- 服务器目录：`/opt/inteliscope`
- Docker Web 端口：`127.0.0.1:8080`

## 1. 登录访问

多人 Service API 始终要求应用账号登录。如果 Nginx 另行开启 Basic Auth，首次访问还会先弹出浏览器原生登录框。

- 应用账号由管理员创建，角色分为 `owner/admin/member/viewer`。
- Nginx Basic Auth 是可选的站点外层密码，与应用账号和 AI API Key 都不同。
- 浏览器会缓存 Basic Auth 登录状态；要退出通常需要关闭浏览器，或清理站点登录缓存。

注意：Nginx Basic Auth 不能替代应用登录和角色权限；`viewer` 只读，成员管理与全局配置需要 `owner/admin`。

## 2. 信息流页面

顶部标签用于切换阅读视图：

- `精选`：今天达到精选阈值的内容，适合默认扫读。
- `全部`：今天进入信息流的所有内容。
- `稍后读`：当前账号标记为稍后读的条目，状态保存在 Service DB。
- `历史`：从当前用户最近 snapshot 留存中回看已经离开最新 Feed 的条目。
- `日报`：达到每日推送阈值的内容。
- `订阅`：管理公共源市场、我的订阅、私有源、刷新任务和成员（按角色显示）。
- `配置`：维护信源、标签、AI 模型、阈值和推送设置。

左侧筛选支持：

- 关键词搜索：匹配标题、摘要、理由、标签。
- 最低分：按 AI 分数过滤。
- 频道/主题：按 Hub taxonomy 筛选。
- 来源：按具体信源过滤。
- 只看收藏：只显示当前账号收藏的内容。
- 隐藏已忽略、未读优先：使用当前账号的 item state。

条目按钮：

- `打开原文`：跳到原始链接。
- `标记已读`：记录当前账号已阅读该条目。
- `复制摘要`：复制条目的摘要内容。
- `收藏`：保存或取消当前账号的收藏状态。
- `稍后读`：保存或取消当前账号的稍后读状态。
- `忽略`：把条目标为已忽略，可配合“隐藏已忽略”筛选。

选中首篇、切换条目或重新加载页面都不会自动标记已读；只有用户点击一次 `标记已读` 才 PATCH Service API。已读后按钮显示 `已读` 并禁用，不会再次点击取消。

右上角 `获取新内容` 会创建 `user_feed_refresh`，不是只重新读取旧 snapshot。任务 queued/running 时按钮会禁用并轮询；完成后页面自动加载新 Feed，同一账号重复提交会复用已有任务。

### 2.1 自动更新信息流

在 `订阅` 页顶部使用“自动更新信息流”卡片：

- 每个用户独立设置，默认关闭；viewer 只能查看。
- 周期固定为 1、3、6、12 或 24 小时，默认 6 小时。周期只决定何时刷新，不缩短配置中的内容抓取时间窗口。
- 首次开启会在下一个 Worker 调度 tick 创建任务；关闭后不再创建新任务，已经 running 的任务会继续完成。
- 卡片显示上次自动刷新、任务状态、产出条数、`partial` 的问题摘要、下次刷新和 Worker 状态。Worker missing/stale、配额耗尽、无有效订阅或 source fetch 冲突会显示明确状态。
- `立即刷新` 始终保留，并与自动任务共用去重、轮询、配额和 Feed 更新逻辑。

默认 UI 不提供站内原文预览、偏好反馈、Archive 分析或 Graph 入口；订阅控制台也不请求 archive/source-quality。

## 3. 今日与历史规则

多人 Service 使用 `data/service.db` 中当前用户的 Feed snapshots：

- `最新` 读取当前用户最新 snapshot。
- `历史` 从当前账号自己的近期 snapshots 构造，避免把仍在最新 Feed 的内容重复显示。
- 历史条目会补充当前账号最新的收藏、稍后读、已读和忽略状态；精确响应与留存算法以 `API_CONTRACT.md` 为准。

旧 CLI 的 `data/site/history-data.json` 是全局静态发布兼容文件，与多人 Service 历史不是同一数据层；默认 Service UI 不读取它，也不按“第二天搬运文件”的规则生成历史。

## 4. 配置页面

配置页用于维护项目行为，不建议随便改。

常用区域：

- 密钥管理：owner/admin 可新增或轮换 AI/Apify Key；真实值提交后永不回显。
- AI 模型：配置 provider、model、Key 引用、单篇概括字数和输出 token 上限。
- AI 固定大类：用于评分 Prompt 和精选逻辑，建议保持稳定。
- 个人标签：自由添加个人偏好标签，只用于关注和筛选。
- 评分阈值：控制精选、每日推送和首页最低分。
- 信源配置：新增 RSS、GitHub、Reddit、Telegram、Apify 社交订阅等。
- Webhook：配置每日推送目标。

保存规则：

- SQLite 与配置 JSON 只保存密钥引用，不保存真实值。
- 网页写入的真实值只进入本地 `data/secrets.env`，文件权限固定为 `0600`，页面以后只显示名称和“已设置”。
- `data/secrets.env` 已被 Git 和 Docker 构建忽略；API 与 Worker 会在任务前热加载，轮换后无需重启。
- 后台会校验 URL、标签、环境变量名和订阅类型。
- 保存失败时页面会返回原因。

## 5. Apify 社交订阅

当前 Apify 用于抓公开社交平台内容，例如：

- X 公开账号或关键词。
- Instagram 公开主页或 hashtag。
- Facebook 公开 Page、公开 Group、公开帖子 URL。
- Telegram 公开频道。

限制：

- 不抓私密频道、私密群组、好友流。
- 不使用 cookie、账号密码或 session。
- Apify 会消耗额度，测试订阅也会消耗少量额度。

如果额度紧张：

- 只保留必要订阅。
- 把个人兴趣类内容设置为 `个人关注（跳过 AI）`。
- 降低每个订阅的抓取数量。

## 6. AI 模型用途

AI Key 主要用于：

- 给内容打 0-10 分。
- 生成中文摘要。
- 生成内容判断理由。
- 归类到固定大类。
- 判断是否进入精选和每日推送。

默认单篇只发送最多 1000 字正文和 1500 字评论，模型输出最多 800 token；最终概括硬限制为 200 字。模型失败、空响应或“仅收集”模式会回退到来源摘要、正文片段或标题，Feed 不会出现空概括。

个人标签不会进入行业评分 Prompt；它只表达个人偏好和筛选需求。

## 7. Service 与旧 CLI 数据边界

当前多人 Service 的产品边界是信息获取和 Feed 留存：

- Service UI/API 只以用户 `service.db` snapshot 作为 latest/history 数据源。
- Archive analytics、source-quality、偏好 feedback 和 Graph 仅保留兼容接口，不驱动默认 UI、Feed 排序或个性化推荐。
- `/api/archive/graph` 固定返回 disabled 安全空响应，Service 页面没有 Graph 入口。

旧 CLI/scheduler 可选继续生成全局 `data/site/history-data.json`、`data/horizon.db` 和 `data/site/article-graph.json`。这些是 legacy compatibility 输出，只由旧 publisher 使用，不会被多人 Service UI/API 当作兜底数据源。

## 8. 每日推送

以下是旧 CLI/scheduler 的可选分发规则，不属于默认 Service 信息获取与 Feed 留存链路：

- 时区：`Asia/Shanghai`
- 每天 `08:30` 生成每日推送。
- 分数高于每日推送阈值的内容进入推送。
- 增量轮询期间只更新 Web 页面，不重复发每日推送。

手动测试：

```bash
cd /opt/inteliscope
docker compose run --rm horizon --hours 24
```

查看日志：

```bash
cd /opt/inteliscope
docker compose logs -f horizon-scheduler
```

## 9. 管理员运维

进入服务器：

```bash
ssh vps-tokyo
cd /opt/inteliscope/current
```

查看服务：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f horizon-api horizon-worker
```

查看当前 release：

```bash
./scripts/release_vps.sh status
```

检查本机反代目标：

```bash
curl -I http://127.0.0.1:8080/
```

普通公网升级从干净且与 `origin/main` 完全一致的本地 `main` 执行 `./scripts/release_vps.sh release vX.Y.Z`。它会复用该 SHA 已成功的 main Test Gate，在 CI 等待期间并行构建本地 `linux/amd64` 镜像，并行断点续传源包和镜像；main 绿灯后才推 Tag，Tag 隔离 smoke 通过后才切换 API/Worker。切换前会确认没有活跃任务、scheduler 未运行，并在线生成 `0600` 数据库和环境备份；readiness、Worker、前端资源或公网 revision 验证失败会自动回滚。含数据库迁移的版本必须先走对应迁移手册，普通发布会拒绝隐式迁移。不得在 VPS 从脏工作区执行 `up-latest.sh`，也不得在 VPS 构建项目。首次空数据库引导才使用旧的 `release_rc1.sh`。

## 10. Nginx 项目密码

只给 Inteliscope 这个项目加密码时，把 Basic Auth 放到反代 `127.0.0.1:8080` 的 `location /` 中。

核心配置：

```nginx
location / {
    auth_basic "Inteliscope";
    auth_basic_user_file /etc/nginx/.htpasswd_inteliscope;

    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

生成密码文件：

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd_inteliscope friend
sudo nginx -t
sudo systemctl reload nginx
```

验证：

```bash
curl -I https://rb.jiefs.top/
curl -I -u friend:你的密码 https://rb.jiefs.top/
```

预期：

- 不带账号密码返回 `401`。
- 带账号密码返回 `200`。

## 11. 常见问题

页面看不到内容：

- 点右上角清除筛选按钮。
- 检查最低分是否过高。
- 切到 `全部` 或 `历史` 视图。
- 确认订阅已启用，并在「订阅」页刷新当前用户 Feed。
- 查看 `docker compose logs -f horizon-api horizon-worker`。

readiness 返回 `migration_required`：

- 这表示当前访问的数据库尚未完成 Feed v2 迁移；迁移不会随应用启动自动执行，应以 migration marker/readiness 为准。
- 在停服和备份后显式运行 `scripts/migrate_user_feed_v2.py --apply`，再检查外键与首次刷新。当前部署已于 2026-07-11 完成该流程，但其他数据库仍需分别执行。

配置保存失败：

- 检查 URL 格式。
- 检查标签是否在固定大类或个人标签库中。
- 检查 `.env` 是否有对应环境变量。

社交源抓不到：

- 确认目标是公开内容。
- 确认 `APIFY_TOKEN` 已设置。
- 降低抓取数量后再测试。

AI 摘要没有生成：

- 在配置页确认所选 AI Key 显示“已设置”。
- 检查 `ai.provider`、`ai.model`、`ai.base_url` 是否匹配。
- 查看 Worker 日志中的模型请求错误；Gemini 限流时会保留受长度限制的来源概括，并在后续刷新重试 AI。
