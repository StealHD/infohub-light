import type { Subscription } from '../../api/types'

export function informationSourceLabel(source: Subscription & { source_platform?: string }): string {
  const platform = (source.source_platform || source.source_type || '').replace(/^(twitter|x)$/i, 'X')
  const name = source.source_display_name || '订阅来源'
  if (!platform) return name
  return name.toLocaleLowerCase().startsWith(`${platform.toLocaleLowerCase()} ·`) || name.toLocaleLowerCase() === platform.toLocaleLowerCase()
    ? name : `${platform} · ${name}`
}
