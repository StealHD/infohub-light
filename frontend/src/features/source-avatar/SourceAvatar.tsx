import type { ReactNode } from 'react'

import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Icons,
} from '../../design-system'

type SourceAvatarProps = {
  name: string
  avatarUrl?: string | null
  platform?: string
  className?: string
}

const LOCAL_AVATAR_URL = /^\/api\/media\/[A-Za-z0-9_-]{1,128}$/

const sourceMark = (name: string) => {
  const normalized = name.trim().replace(/^[@#]/, '')
  return Array.from(normalized || '?').slice(0, 2).join('').toLocaleUpperCase()
}

function platformMark(platform: string, name: string): ReactNode {
  const normalized = platform.trim().toLocaleLowerCase()
  if (normalized.includes('github')) return 'GH'
  if (normalized.includes('reddit')) return <Icons.MessageCircle size={16} aria-hidden="true" />
  if (normalized.includes('instagram')) return 'IG'
  if (normalized.includes('youtube')) return 'YT'
  if (normalized.includes('telegram')) return <Icons.Send size={16} aria-hidden="true" />
  if (normalized === 'x' || normalized.includes('twitter')) return 'X'
  if (normalized.includes('rss')) return <Icons.Rss size={16} aria-hidden="true" />
  return sourceMark(name)
}

export function SourceAvatar({
  name,
  avatarUrl,
  platform = '',
  className,
}: SourceAvatarProps) {
  const localAvatarUrl = avatarUrl && LOCAL_AVATAR_URL.test(avatarUrl)
    ? avatarUrl
    : null
  return <AvatarRoot className={className}>
    {localAvatarUrl && <AvatarImage src={localAvatarUrl} alt={name} />}
    <AvatarFallback role="img" aria-label={`${name} 来源标识`}>
      {platformMark(platform, name)}
    </AvatarFallback>
  </AvatarRoot>
}
