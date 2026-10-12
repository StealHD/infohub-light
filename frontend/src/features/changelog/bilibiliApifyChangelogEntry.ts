import type { ChangelogEntry } from './changelogTypes'

export const bilibiliApifyChangelogEntry: ChangelogEntry = {
  date: '2026-10-10',
  title: 'Bilibili 订阅接入 Apify 主备',
  summary: 'UP 主公开视频更新使用 ActorOps 主用与备用线路，现有订阅和历史继续保留。',
  items: [
    { title: '主备统一管理', description: '管理员在 ActorOps 配置 Bilibili 主用与备用；候选经过固定版本、目标归属及费用验证后生效，获取失败按现有规则切换备用。' },
    { title: '旧订阅切换', description: '旧库经显式切换工具补齐路线及绑定后进入准备状态；具备本地证明并启用路线后恢复获取，主动停用的来源保持停用。' },
    { title: '阅读状态连续', description: '来源、订阅及视频身份延续原有规则，保留历史、收藏与已读状态；获取不再依赖 RSSHub。' },
    { title: '准备状态可见', description: '订阅卡片显示 Bilibili UP 主与等待 Actor 验证状态，未就绪时暂停获取并提供主备配置入口；不会再误报来源不存在。' },
    { title: '首次主用配置', description: '新 Bilibili 路线可直接准备首个主 Actor；计划覆盖待验证来源，逐一实测并结清费用后应用，主动停用的来源不参与。兼容可空字段、用户视频操作、资料与视频混合输出及每位 UP 的视频数量限制。' },
  ],
}
