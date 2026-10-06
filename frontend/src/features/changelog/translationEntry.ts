import type { ChangelogEntry } from './changelogTypes'

export const translationEntry: ChangelogEntry = {
  date: '2026-10-06', title: '卡片正文支持按需中文翻译',
  summary: '使用已配置的大模型翻译各来源的已抓取正文，在原文下方阅读译文。',
  items: [
    { title: '一键翻译', description: 'Feed、专题速览、收藏和历史的卡片右下角新增翻译入口，原文和图片保留，译文可独立收起；只有片段时明确提示范围。' },
    { title: '缓存与恢复', description: '译文按账户保存 30 天，重复点击和刷新复用现有任务；正文或模型变化后重新翻译，失败可就地重试。' },
  ],
}
