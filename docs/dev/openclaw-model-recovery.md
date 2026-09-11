# OpenClaw 模型分叉与失败恢复

## 生产只读证据（2026-09-11）

Service 为 `2.6.17 / 497d85a52fd3`，Gateway 为 `2026.9.2`。上海时间 15:15:42–15:16:37 的运行 `43701ffc-6987-4a62-9ac7-7e8a9b1a8ddb` 耗时 55779 ms，最终 Gemini 3.7 Flash 返回 429 / RESOURCE_EXHAUSTED，此前两次 503。对应 trajectory 的 aborted、externalAbort、timedOut、idleTimedOut、timedOutByRunBudget 均为 false。

只读查询范围为这次运行及其父子会话元数据，没有复制对话正文或凭据。子会话没有 providerOverride/modelOverride，父会话有明确 Gemini 覆盖；默认配置为 DeepSeek。Gateway 的默认模型 patch 清除覆盖；describe 使用当前默认模型，运行 resolveStoredModelOverride 又继承父会话，形成展示和执行分歧。最初 DeepSeek 的 HTTP 200 日志没有该运行关联，不能据此认定本轮先使用 DeepSeek 再故障切换。

本地旧代码回归同时证明：Google 配额原文和 errorKind=rate_limit 都被转接分类为 RELAY_REQUEST_FAILED；历史 stopReason=error 被投影为 sent。Gateway 的历史安全投影会移除原始错误字段并加入通用英文提示，因此缺失的历史原因不能凭文本猜回。

## 兼容恢复

产品行为以 [Gateway 合同](../contracts/api/openclaw-gateway.md) 为准。用户主动切换模型继承原上下文，只有“新对话”开启空白上下文；不额外显示成功提示。旧分叉继承异常时重新选择模型，若仍失败则需修补 Gateway，原会话、草稿和附件保留且不会自动发送。不要删除旧会话、直接改 Gateway SQLite、修改默认模型或增加超时来绕过。

模型额度问题需要提供方恢复额度；代码只能准确呈现原因。实际模型缺少本次运行证据时显示未知。已有安全诊断在当前浏览器会话存储内按账号/Gateway/会话隔离，换浏览器或上游已抹去原因时可能无法恢复具体原因。未知结果先按运行编号核对，不自动重放。

## 本地验收与发布边界

`tests/openclaw_recovery_gateway.py` 编码线上已确认的 describe/执行差异；浏览器验收通过临时数据库、真实 Service 认证/绑定和生产 WebSocket relay 接入该 Gateway，模型调用为受控记录。无真实模型、通知和生产写入。

本轮在 `codex/automation-analysis-recovery` 本地实现；不部署 VPS，不修改已安装 Gateway 包，不处理三条旧自动化预览。没有新增数据库迁移；本分支此前的 global 45 仍须未来发布时显式执行。本地通过不代表生产已恢复，未来上线须按仓库发布流程及明确授权单独完成生产验收。

## Gateway 安装包兼容补丁（未来部署时明确执行）

`scripts/patch_openclaw_fork_model.py --package-root <OpenClaw 安装目录>` 默认只检查，不写文件。仅接受 2026.9.2/2026.9.3 和精确匹配的分叉实现。后续已授权发布时加 `--apply`：保存带原始摘要的私密备份，原子替换目标模块；随后按运维流程重启 Gateway。不是 Service 启动或接入安装的自动步骤。升级安装会覆盖补丁，必须重新检查，未知版本拒绝修改。

补丁只在已有分叉事务通过模型解析后，给显式请求设置 providerOverride、modelOverride、user 来源与 resolved 路由；不触碰上下文复制、权限、通知或模型额度。回滚时停止 Gateway，核对备份摘要后恢复原文件并重启。旧危险分叉通过用户重新选择模型生成新的正确分叉，不批量重写运行库。

## 最终验证记录

定向后端、前端、类型、ESLint、代码规模及控制文件检查通过。最终桌面/手机真实 Service 转接用例 2 项通过（21.3 秒），包含保留上下文、同模型重选、一次发送和刷新失败诊断；最终方案未重复扩展平板验证。生产 2026.9.2 与本地 2026.9.3 的安装源码只读检查通过，补丁仅在临时目录应用验证。

完整 preflight 未全绿：首次为决策索引字节上限，唯一重跑在后端末段因新增 E2E 映射预期漏更新而失败（388.992 秒）。均已修复并定向复验，通过预算约束不做第三次完整运行；不能将此记录当作正式发布 Gate。
