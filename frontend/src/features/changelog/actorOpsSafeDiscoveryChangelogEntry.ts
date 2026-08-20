import type { ChangelogEntry } from './changelogTypes'

export const actorOpsSafeDiscoveryChangelogEntry: ChangelogEntry = {
  date: '2026-08-20',
  title: '替换或新增 Actor 使用免费搜索与双确认',
  summary: '管理员可一键启动一次免费候选搜索；付费验证与最终生效继续分两次明确确认，系统不会自动扣费或改写主备。',
  items: [
    { title: '一次点击只做免费搜索', description: '“自动搜索候选（免费）”每次只创建一个 Discovery Job，内部最多三轮官方 Store 查询；失败或候选不足时不会自动重复。' },
    { title: '付费与生效分别确认', description: '付费前会展示冻结 Actor、逐项上限和批次总上限并要求确认 1/2；验证和费用对账完成后，仍需确认 2/2 才会原子更新目标槽位。' },
    { title: '现有线路与历史证据保持不变', description: '免费搜索和付费验证期间继续使用当前主备；旧实验流程留下的费用、验证和运行证据保留审计，不会重放或删除。' },
    { title: '所有单次 Actor 上限统一为 $0.10', description: 'YouTube 和 Instagram 线路可使用最高 $0.10；X 保留当前较低配置，任何入口和真实运行都不能超过 $0.10。' },
  ],
}
