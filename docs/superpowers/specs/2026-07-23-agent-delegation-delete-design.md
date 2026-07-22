# 已吊销助手连接单条删除设计

## 1. 目标

在 `/agents` 的“我的连接”中，允许当前用户永久删除自己选中的一条已吊销 Remote MCP delegation 记录。删除不得影响其他连接，也不得把有效令牌的吊销与记录删除合并成一个不可区分的动作。

非目标：不删除 OpenClaw Gateway 浏览器配对，不批量清理连接，不修改令牌期限、权限或最多五个有效连接的规则，不改变 Remote MCP 调用认证。

## 2. 已确认根因

现有 `DELETE /api/me/agent-delegations/{id}` 是幂等吊销接口：首次和重复调用都只设置 `revoked_at`。存储层没有用户作用域的单条删除方法，前端对非 active 记录禁用“吊销”按钮，因此已吊销记录没有删除路径。

## 3. 方案比较

1. **独立删除记录接口（采用）**：保留现有吊销接口的幂等语义，新增仅接受已吊销记录的显式删除路径。安全边界清晰，也不会因网络重试把一次吊销升级为物理删除。
2. 重复调用现有 DELETE 时删除：改动少，但吊销响应丢失后的自动重试可能误删记录，破坏现有幂等合同。
3. 增加 `deleted_at` 软删除：保留审计能力，但需要新 schema/migration，并超出“删除一条已吊销连接”的最小范围。

## 4. API 与存储

- 保留 `DELETE /api/me/agent-delegations/{id}` 为幂等吊销。
- 新增 `DELETE /api/me/agent-delegations/{id}/record`，只删除当前用户拥有且 `revoked_at IS NOT NULL` 的一条 delegation。
- 成功返回 `200 {"ok":true,"data":{"deleted":true}}`。
- 当前用户不存在该记录时返回 `404 not_found`；记录仍有效或仅到期但未吊销时返回 `409 agent_delegation_not_revoked`。
- 删除 `agent_delegations` 行时，SQLite 依据既有外键 `ON DELETE CASCADE` 删除该 delegation 的 proposal；其他 delegation、用户、订阅、Feed 与来源不受影响。
- 存储方法必须同时使用 `id` 与 `user_id` 限定目标，不提供管理员跨用户删除。

## 5. 页面交互

- active 行继续显示“吊销”；revoked 行将该位置替换为“删除”；expired 行不新增删除能力。
- 点击“删除”先打开“删除已吊销连接”确认框，明确说明只删除当前这一条记录且不可恢复。
- pending 时锁定确认动作；成功后关闭弹窗、刷新 delegation 查询并显示“已删除连接记录”；失败时保留该行和弹窗并显示真实 API 错误。
- 复制配置、重命名、访问权限展示及其他连接卡片行为保持不变。

## 6. 验证

- 存储测试覆盖：有效记录不可删、已吊销记录可删、其他用户记录不可删、只删除目标记录。
- API 测试覆盖：原吊销仍幂等；新接口在吊销前返回 409，吊销后删除并从列表消失；跨用户返回 404。
- 前端测试覆盖：active 行只调用吊销；revoked 行显示删除确认框并只把目标 ID 传给删除 API；取消、pending、成功刷新与失败保留状态。
- 运行定向 Python/Vitest、TypeScript、production build、`test_gate full`，然后以不可变镜像重建本机 API/Worker 并验证健康、数据库完整性和功能开关。

## 7. 回退

回退代码与镜像即可恢复只吊销不删除的旧行为。该方案不新增数据库列或迁移；已经由用户明确删除的记录不通过代码回退自动恢复，因此本地容器切换前继续保留 SQLite 备份。
