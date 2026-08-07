# Acquisition Loop v1 实现报告

## 结果

本期已在本地完成 Feed 获取状态、来源/订阅编辑、来源测试预览、失败诊断和 source priority 全链路。默认产品仍只包含订阅、抓取、Feed 展示与留存。

## 关键行为

- 阅读页统一展示 queued/running/succeeded/partial/failed，并可从页面重载恢复当前用户任务。
- 8 种 registry 来源通过字段元数据生成创建/编辑表单；source type 创建后不可修改。
- subscription override 支持频道、主题、个人标签、分析模式、priority `0..100` 和启停。
- `保存` 不创建任务；`测试连接` 创建 `source_test`；`保存并重新抓取` 创建 `source_fetch`。
- source config/secret 变化重置健康为 `unknown`；普通展示和 subscription override 不重置。
- 排序使用 score、source priority、发布时间和 id；重复文章保留完整 provenance 并取最高 priority。
- issue 与测试样例经过 URL/凭据脱敏、HTML escaping 和长度限制。

## 跨用户异步修复

独立 UI 审查发现编辑、刷新、重试和最近任务查询可能在登录用户切换后继续写入共享状态。修复后所有相关动作捕获 `user_id + action_generation`，每次异步响应后重新确认当前用户；旧响应不得更新 Feed activity、任务轮询、按钮、消息或订阅控制台。

新增/更新的 RED 用例覆盖：

- 来源和订阅 PATCH 延迟返回后切换用户。
- source job、Feed refresh 和 retry 延迟返回后切换用户。
- 最近任务远程返回后切换用户。
- 缓存中位于前 8 条之外的目标任务提升。
- workspace 前 20 条任务属于其他用户时仍从 schedule 恢复当前用户任务。

## 验证

- `node --test tests/reading_ui_behavior.test.cjs tests/subscription_job_ui_behavior.test.cjs`：54/54 通过。
- `./.venv/bin/pytest -q`：627 项收集，全部通过。
- Docker、VPS 与公网浏览器证据统一记录在 `release-rc1-report.md`，不得用本地测试代替发布结论。

## 当前状态

代码与本地完整回归完成；等待 RC1 镜像检查、不可变 release commit 授权、VPS staging/promote 和 `rb.jiefs.top` 公网验收。
