import type { ChangelogEntry } from './changelogTypes'

export const skillExecutionEntry: ChangelogEntry = {
  date: '2026-09-26', title: '补齐已开放 Skill 的执行能力',
  summary: 'Skill 可读取说明与参考文件，book-skill 可使用浏览器；同步会核验已有会话的实际工具是否就绪。',
  items: [
    { title: '浏览器端点冲突修复工具', description: '新增管理员运维修复命令，默认仅预览本机浏览器控制地址与访问策略的冲突；显式应用后继续限制网页访问本机、内网与元数据地址。普通部署与 Skill 同步不会自动修改此配置。' },
    { title: '消息保留 Skill 标签', description: '发送后在问题气泡内显示本次选择的 Skill；刷新、重连和历史会话恢复时保留标识，不将选择标签当作已执行证明。' },
    { title: '受限读取与浏览器', description: '开放 Skill 后补齐工作区及已解析 Skill 目录的只读能力，book-skill 同时取得浏览器能力；保留主机文件、Shell 和文件修改限制。' },
    { title: '已有连接可同步或收回', description: '部署更新后，管理员在管理开放范围点击“同步执行能力”即可修复；已有会话的实际工具未就绪时显示同步失败并允许重试。收回 Skill 时撤回对应受管能力。' },
  ],
}
