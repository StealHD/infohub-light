import type { ChangelogEntry } from './changelogTypes'

export const instagramMediaEntry: ChangelogEntry = {
  date: '2026-09-15',
  title: 'Instagram 帖子图片与视频封面适配',
  summary: '有效帖子中的图片不再依赖旧候选的缩略图映射，继续使用受保护的本地缓存和图集预览。',
  items: [
    { title: '单图与图集', description: '支持单图、图集及多尺寸择优，每帖最多缓存 6 张，保留原始顺序与已知总数；部分下载失败仍可查看已缓存图片。' },
    { title: '视频只显示封面', description: 'Reels、视频帖保留视频分类，混合图集保留媒体类型信息，不下载视频本体。' },
    { title: '指定历史帖安全补图', description: '维护命令先预览后执行，只复用已保存地址或可验证的既有 Dataset；不启动新的付费抓取、不改正文分析，也不发送通知。上游图片或 Dataset 不可用时保留文字并报告原因。' },
  ],
}
