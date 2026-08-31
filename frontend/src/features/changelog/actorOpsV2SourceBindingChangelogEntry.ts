import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2SourceBindingChangelogEntries: ChangelogEntry[] = [{
  date: '2026-08-31',
  title: '停用的平台来源可以从来源设置恢复',
  summary: '订阅仍开启但来源或 Binding 已停用时，管理员和私人来源所有者可以显式恢复，不再卡在只读冲突状态。',
  items: [
    { title: '恢复入口回到来源设置', description: 'X、Instagram 与 YouTube 的既有来源会显示“启用来源”；重新启用后，系统先恢复 Binding，再使用当前本地证据核验并启用来源。' },
    { title: '恢复不触发抓取或费用', description: '保存来源不会创建 Job、启动 Actor 或产生费用；显式停用仍不会被 Worker 自动推翻，自动更新继续使用用户已有的全局或单源计划。' },
  ],
}, {
  date: '2026-08-23',
  title: 'OpenClaw 可以订阅全部支持来源',
  summary: '来源库里的可见来源都能直接订阅；GitHub/Reddit 用户、Hacker News、X 与 Instagram 也可由订阅管理连接新建。',
  items: [
    { title: '用户来源不再折叠', description: 'GitHub 仓库发布与用户动态、Reddit 社区与用户现在分别识别；RSS/网站、Bilibili、YouTube、Telegram 和 Hacker News 保持各自的安全输入。' },
    { title: 'X 与 Instagram 自动准备', description: '网页和 OpenClaw 都会在创建后保存订阅，并只用本地目标、Manifest 与输入兼容性自动核验；证明通过即启用来源，不抓取、不启动付费 Actor。证据不足会保留订阅并显示准备原因；Apify 来源默认每次获取 3 条，用户仍可调整。' },
    { title: '确认和隔离保持不变', description: '每个来源仍单独 prepare、展示完整预览并等待准确确认短语；裸 @账号未说明 X 或 Instagram 时会先询问平台，现有可见来源只使用来源库返回的 ID。' },
  ],
}, {
  date: '2026-08-22',
  title: '平台来源改用 ActorOps v2 Binding',
  summary: 'X、Instagram 与 YouTube 的创建、修改、停用和抓取不再依赖旧 ActorOps 来源映射；待验证来源不会提前运行。',
  items: [
    { title: '新来源先验证再启用', description: '平台来源创建后先保持停用并生成 pending Binding；修改账号或频道会原子清除旧目标的选择与水位证据，验证当前目标后才可启用。' },
    { title: '普通编辑不重复验证', description: '获取条数、分析模式、名称、说明、频道与主题变化不会增加 Binding 版本，也不会清除最近成功或水位。' },
    { title: '停用不再回退旧路径', description: 'X 与 Instagram 在 Route 未启用时明确阻止抓取；YouTube 只在适用时使用免费且受公共网络策略约束的 RSS fallback，不创建付费 Attempt。' },
  ],
}]
