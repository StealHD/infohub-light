# ActorOps 探测中断恢复

Maintenance/Replacement 新 Probe 的 `logical_job_id` 关联实际 Worker Job，计划与 slot 仍由 `attempt_group_id` 保留。created/starting Probe 只有精确同 workspace 的终态 owner 才进入中断恢复；旧记录可用终态 Job 结果中的 exact Attempt ID 关联。无远端预留的 created Probe 自动取消并释放预算；存在预留或 starting 状态不得推断零费用，继续只读对账，绝不重发启动。

ActorOps 返回失败结果时，Job 顶层和完成事件保留安全 `error_code`；Repair 结果可附带 `next_attempt_at`。blocked/recovery_required 仍不是成功，未知异常只记录安全类型与代码位置，不返回上游原文。候选槽位释放、候选已接管或出现可按既有政策替换的已确认故障时，Worker 可提前唤醒容量受阻 Repair；仍重验权限、费用、Binding 证明和最后一路保护。

Apify 固定 API 的 Catalog、Probe 与对账客户端统一遵循系统/环境代理，与正常抓取一致；注入的测试 Transport 优先。公共 URL 抓取策略不变。内部传输失败保留原错误和执行事件，不触发候选替换或探测预算评估。启动结果不明仍只对账；已最终证明未启动的原 Attempt 在原 Job 重放时返回 `apify_request_not_started`（不可重试），不再归类为路由耗尽。同一 Job/Binding/Candidate 的唯一约束保持不变，下一次正常调度的新 Job 才重新经过凭据、预算和费用屏障申请启动。历史 Attempt、费用事实不重写。

ActorOps 先结算 Run、Key 池随后对账的顺序也必须收敛。仅未知启动类阻塞、同 workspace/被阻塞凭据在阻塞后产生的零费用最终未启动证据，且没有任何采集域未终态 Run（含遗失 Key 关联）时，正常维护释放过时池阻塞；重复执行不增加 generation，不修改 Run 历史、不新增远端调用。其他阻塞原因、新阻塞、已知 Run 或不完整费用不能据此解锁。

Worker 领取任务前的 Key 池对账按 workspace 限时 20 秒，超时返回 `apify_pool_reconcile_deadline`，保留已落账事实与未决保护，下一轮继续；超时不等于费用为零，也不授权新 Run，其他 workspace 和任务领取可继续。

Instagram 混合结果按原 Manifest 逐行验证：仅来源身份不匹配的行可隔离，且剩余行必须至少产出一条窗口内有效内容，再做整批验证。全部不匹配、目标不可用、非法 URL 或结构错误仍失败。通用结果端口 `NormalizedBatch.rejected_identity_rows` 默认为 0；隔离时执行轨迹记录计数和 `actorops_partial_identity`，ExecutionResult 同步降级原因，不宣称完整图集或完整抓取。只有通过验证的行参与媒体关联、头像和水位；请求回显不构成作者/共同作者证据。此能力按结构和字段映射生效，不按 Actor 名单分支，既有显式共同作者证明仍有效。原终态失败 Attempt 不因解析器升级改写。
