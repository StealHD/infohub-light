## ActorOps auto-pool 退役与 global 25 兼容

1. 单槽新增/替换只复用现役流程：一次管理员动作创建至多一个免费 Discovery Job，Discovery 内最多执行三轮官方 Store 查询；浏览器只通过既有 `pool-candidates/refresh`、Canary plan/batch 与 staged activate 接口继续。付费 Canary 必须显示冻结候选和精确总上限并使用确认 1/2；费用终结后，`verified-pool-activation` 或 Stage apply 还必须携带新的 `apply_id` 与 `confirmation="确认启用 Actor 主备"`，完成确认 2/2 才能改变活动池。
2. `/api/admin/apify-routes/{route_id}/auto-pool` 与 `/api/admin/apify-auto-pool-runs/{run_id}` 不属于当前接口，不进入 OpenAPI。服务端不得生成 approval/apply ID 代替操作者确认，不得按 `$0` shortfall 自动循环 Discovery，也不得在 Worker Job 完成后自动批准付费或生效。
3. 实验性 global 25 marker/table 若已存在，只保留为 operator-owned 惰性历史证据；普通 API、Worker、readiness、maintenance 与 fresh-database bootstrap 均不得读取、要求、创建、迁移、清空或删除它。只有显式离线退役工具可在 API/Worker 停止、heartbeat 过窗、无 unknown-start 且费用全部终结后，以 `0600` backup 和单事务把遗留非终态 auto-owned Job/Discovery/run 安全终态化；Validation、Attempt、Batch、Run 和费用账本不得改写或删除。
4. 现役 ActorOps migration 链止于 global 24 `apify_actor_pool_management_v22`。global 25 永久保留且不得复用；后续全局迁移从 26 开始，并以 global 24 的精确 marker/checksum/shape 为前置，同时容忍数据库是否存在惰性 global 25。
