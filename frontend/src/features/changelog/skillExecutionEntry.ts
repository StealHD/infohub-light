import type { ChangelogEntry } from './changelogTypes'

export const toolActivityEntry: ChangelogEntry = {
  date: '2026-09-27', title: 'Agent 显示当前工具动作',
  summary: '运行步骤会显示桌面查书及站点验证动作。',
  items: [{ title: '工具进度更清楚', description: '只显示固定动作名称，不展示工具参数或验证内容。' }],
}

export const skillExecutionEntry: ChangelogEntry = {
  date: '2026-09-26', title: '补齐已开放 Skill 的执行能力',
  summary: 'Skill 可读取说明与参考文件，book-skill 可使用浏览器；同步会核验已有会话的实际工具是否就绪。',
  items: [
    { title: '代理浏览器的独立公网出口', description: '为需要代理的托管浏览器提供独立运行环境，仅允许经过校验的公网 HTTPS 访问；个人 Agent 保留原有工具限制。原生桌面浏览器与登录状态不共享，运行环境需管理员显式安装和验收。' },
    { title: '浏览器端点冲突修复工具', description: '新增管理员运维修复命令，默认仅预览本机浏览器控制地址与访问策略的冲突；显式应用后继续限制网页访问本机、内网与元数据地址。普通部署与 Skill 同步不会自动修改此配置。' },
    { title: '消息保留 Skill 标签', description: '发送后在问题气泡内显示本次选择的 Skill；刷新、重连和历史会话恢复时保留标识，不将选择标签当作已执行证明。' },
    { title: 'Skill 读取与桌面流程', description: 'book-skill 可用 VPS 桌面检索、验证码和断点续跑；租约失效后续接原任务。' },
    { title: '已有连接可同步或收回', description: '部署更新后，管理员在管理开放范围点击“同步执行能力”即可修复；已有会话的实际工具未就绪时显示同步失败并允许重试。收回 Skill 时撤回对应受管能力。' },
  ],
}
