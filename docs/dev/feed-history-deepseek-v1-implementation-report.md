# Feed 事件、历史修复与 DeepSeek v1 实施报告

状态：本地代码与历史免费来源修复完成；DeepSeek 实际启用等待轮换 Key。

## 已完成

- Feed 成功通知只消费本次会话观察到的任务事件；`snapshot_created=false` 的 no-op 静默，历史 terminal job 不重放。
- 认证布局级 action feedback 按用户、动作和实体隔离，Feed、订阅、来源、设置、Key 与成员操作提供局部 pending 和失败反馈。
- v5 为稳定内容增加模型无关 input hash 与 unresolved reason；显式 apply 先生成 `0600` SQLite 备份并校验 integrity/foreign keys。
- `content_repair` 强制 AI disabled，只更新已有 article，忽略新文章，不创建 Feed snapshot。免费 RSS/GitHub 可批量；Apify social 保持逐条授权。
- 历史与最新 snapshot 在读取时统一净化媒体字段：只向浏览器返回 `/api/media/*`，旧外链仍留在不可见的审计数据中供修复使用，GET 不改库、不联网。
- DeepSeek Secret metadata、设置 UI、官方模型 id、默认 Key env、同输入哈希安全复用和 retry=0 单次 smoke 已实现。

## 本地数据结果

- v5 inspect 基线：26 条 `excerpt_only`、0 条 captured、0 条缓存媒体。
- apply 备份：`data/backups/service-user-content-v5-20260715T030925608510Z.db`，权限 `0600`。
- Apple、Claude Code Releases、OpenAI News 三个免费修复任务全部 succeeded：23 条转为 captured；每个结果均为 `analysis_calls=0`、`snapshot_created=false`。
- `github:release:353442054` 已恢复 6,671 字符来源正文。
- 余下 3 条属于 X/Instagram 付费来源；Instagram 两个历史媒体签名地址已失效，保持 unresolved，不伪造正文或图片。

## 本地运行与验证

- 已关闭 1 个 Feed 自动计划和 1 个付费 X 单源计划；观察一个 Worker 调度周期后，启用计划和活动任务仍均为 0。
- 本地 `horizon-light-api` 与 `horizon-light-worker` 使用同一最新镜像并保持 healthy；scheduler profile 未启动，VPS Tokyo 未变更。
- 定向门禁和最终 full 门禁均为 22/22，`mapping_miss=false`；桌面与 390px Playwright 为 10 passed、6 个跨项目条件 skipped。
- 真实容器复验：Feed 3 条内容正常显示且历史通知不重放；GitHub 正文 6,671 字符；Instagram 远程图片 URL 数为 0；浏览器 console error 为 0。

## 尚未完成

对话中出现的旧 DeepSeek Key 视为已泄露，未保存、未调用。当前 `data/config.json` 已预置 DeepSeek 目标但保持 `enabled=false`。用户必须在设置页写入轮换后的 `DEEPSEEK_API_KEY`，随后仅运行一次：

```bash
./.venv/bin/python scripts/deepseek_analysis_smoke.py \
  --data-dir data \
  --article-id github:release:353442054
```

smoke 成功后才允许启用全局 AI。VPS Tokyo 仍为 API-only；本次没有修改、部署或启动其 Worker/scheduler。
