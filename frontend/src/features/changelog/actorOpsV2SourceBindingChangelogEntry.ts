import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2SourceBindingChangelogEntry: ChangelogEntry = {
  date: '2026-08-22',
  title: '平台来源改用 ActorOps v2 Binding',
  summary: 'X、Instagram 与 YouTube 的创建、修改、停用和抓取不再依赖旧 ActorOps 来源映射；待验证来源不会提前运行。',
  items: [
    { title: '新来源先验证再启用', description: '平台来源创建后先保持停用并生成 pending Binding；修改账号或频道会原子清除旧目标的选择与水位证据，验证当前目标后才可启用。' },
    { title: '普通编辑不重复验证', description: '获取条数、分析模式、名称、说明、频道与主题变化不会增加 Binding 版本，也不会清除最近成功或水位。' },
    { title: '停用不再回退旧路径', description: 'X 与 Instagram 在 Route 未启用时明确阻止抓取；YouTube 只在适用时使用免费且受公共网络策略约束的 RSS fallback，不创建付费 Attempt。' },
  ],
}
