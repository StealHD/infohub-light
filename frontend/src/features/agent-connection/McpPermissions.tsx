import type { McpPermissions as Permissions } from '../../api/agentConnectionService'

export function McpPermissions({ permissions }: { permissions?: Permissions }) {
  if (!permissions) return null
  const labels = [permissions.read && '读取个人数据', permissions.subscriptions_write && '管理订阅',
    permissions.system_settings_write && '修改系统设置', permissions.workspace_diagnostics && '工作区诊断'].filter(Boolean)
  return <p className="type-meta mt-3 text-muted" aria-label="MCP 权限">MCP 权限：{labels.join('、') || '服务未启用'}。权限随账号角色和服务开关生效。</p>
}
