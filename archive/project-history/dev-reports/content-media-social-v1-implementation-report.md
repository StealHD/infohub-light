# 收藏、站内阅读与社交媒体完整性 v1 实施报告

日期：2026-07-14

## 已实现

- 新增用户隔离的 `user_content_items` 稳定内容索引与 `media_assets` 受保护媒体表。
- 新增收藏列表、按需详情和媒体 API；详情使用 Presentation v2，正文只来自已抓取内容，最多 20,000 字。
- React 增加收藏路由，选择文章不再自动标记已读，支持显式已读/未读；Feed 模式和未读优先按用户持久化。
- Worker 每篇最多缓存 6 张、单张 8 MiB 的验证图片；下载复用公共网络地址固定策略，第三方临时媒体 URL 不进入 snapshot、稳定索引或浏览器响应。来源头像首次成功后复用，身份 key 改变时失效。
- RSS 优先保存 feed 已提供的完整 content，并提取 feed icon、enclosure/media 与正文图片；Instagram 解析多图，首次无头像时执行一次 profile details；X 解析作者头像和媒体。
- X/Instagram profile 采用 `latest_per_source`，新帖替换旧帖，失败或空结果保留旧帖并可越过普通时间窗口。
- 新增显式 v4 迁移：先创建权限 `0600` 的一致性 SQLite backup，再回填旧 snapshot 摘要、记录 marker 并校验完整性和外键。

## 自动化证据

- Python 全量回归 782 项全部通过；legacy Node 63 项全部通过。
- 前端 Vitest 22 files / 82 tests 全部通过；Playwright 13 项通过、11 项按视口条件正常跳过。
- UI contract、ESLint、TypeScript、Vite production build、Python/legacy JS 语法、两份 Compose 配置和 `git diff --check` 已通过。
- Xquik 单元 fixture 覆盖有效帖子、媒体、作者头像、diagnostic/demo 拒绝以及 `$0.01` 参数传递。

## 外部 canary 结果

备用 Key 的真实 `xquik/x-tweet-scraper` canary 在启动阶段返回 `max-items-must-be-greater-than-zero`。Apify 当前公开 pricing 显示 FREE tier 单条为 `$0.015`，因此 `$0.01` cap 无法容纳一个可计费结果。canary 未产生帖子，也未把本地正式 `data/config.json` 从旧 Actor 切换到 xquik。继续真实验证需要操作者明确批准至少 `$0.02` 的单次 cap；`maxItems=1` 仍保持不变。

## 未执行

- 尚未停止本地服务或 apply v3/v4 迁移。
- 只读预检显示 v3 有 51 个 snapshot 待补 content hash，v4 有 24 个稳定内容项待回填。
- 尚未执行 X/Instagram 正式 `source_fetch` 和浏览器图片验收。
- Docker Desktop 当前未运行，因此未重建本地 API + Worker 容器。
- 未修改 VPS 或公网部署。
