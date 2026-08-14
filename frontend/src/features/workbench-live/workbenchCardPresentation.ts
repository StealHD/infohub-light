import type { WorkbenchCardModel } from './workbenchModel'

export function workbenchMediaLabels(card: WorkbenchCardModel) {
  const imageCountLabel = card.totalImageCount > 0
    ? card.mediaTruncated
      ? `${card.totalImageCount} 张图片 · 可查看 ${card.displayImageCount} 张`
      : `${card.totalImageCount} 张图片`
    : ''
  return {
    imageCountLabel,
    mediaPreviewActionLabel: card.mediaTruncated
      ? `打开图片预览，从第 1 张开始，可查看 ${card.displayImageCount} 张，共 ${card.totalImageCount} 张`
      : `打开图片预览，从第 1 张开始，共 ${card.displayImageCount} 张`,
    mediaPreviewBadge: card.mediaTruncated
      ? `可看 ${card.displayImageCount} / 共 ${card.totalImageCount}`
      : `共 ${card.displayImageCount} 张`,
  }
}

export function workbenchTimelineLabel(card: WorkbenchCardModel, feedWindowDays?: number) {
  if (card.item.timeline_bucket === 'today') return '今天'
  if (card.item.timeline_bucket === 'feed') return `近${feedWindowDays ?? 7}天`
  return card.item.timeline_bucket === 'history' ? '历史' : ''
}
