import type { ChangelogEntry } from './changelogTypes'
export const openclawRoleSessionEntry: ChangelogEntry = {
  date: '2026-09-12', title: 'OpenClaw 模型、权限与会话管理统一',
  summary: '分析模型跟随 OpenClaw 配置；MCP 权限跟随账号角色；历史会话可确认后永久删除。',
  items: [
    { title: '模型目录跟随配置', description: '测试下拉框同步个人与分析 Agent 都可用的模型，保留管理员限制，刷新不调用模型。' },
    { title: '一个连接拥有角色对应权限', description: '管理员同时拥有订阅、系统设置和工作区诊断权限，成员可管理本人订阅，Viewer 只读；写入仍受服务开关和确认约束。旧令牌继续有效，托管连接自动更新工具配置。' },
    { title: '历史会话可以删除', description: '侧栏和全部会话菜单可删除闲置历史或归档会话；当前、主会话和运行中会话受保护，删除前必须确认。' },
  ],
}
