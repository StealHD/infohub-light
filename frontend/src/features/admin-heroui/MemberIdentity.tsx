import type { User } from '../../api/types'
import { AvatarFallback, AvatarRoot, OverflowValue } from '../../design-system'

const avatarTones = [
  'from-violet-300 via-fuchsia-300 to-rose-400',
  'from-emerald-300 via-teal-300 to-blue-500',
  'from-amber-200 via-orange-300 to-rose-500',
  'from-sky-200 via-cyan-300 to-violet-500',
] as const

function avatarTone(username: string) {
  let hash = 0
  for (const character of username) hash = ((hash << 5) - hash + character.codePointAt(0)!) | 0
  return avatarTones[Math.abs(hash) % avatarTones.length]
}

export function MemberIdentity({ member }: { member: User }) {
  const name = member.display_name || member.username
  return <div className="flex min-w-0 items-center gap-3">
    <AvatarRoot aria-hidden="true" className={`size-10 shrink-0 bg-gradient-to-br ${avatarTone(member.username)} shadow-sm ring-1 ring-white/10`}>
      <AvatarFallback className="type-control bg-transparent text-black/70">{name.trim().slice(0, 1).toUpperCase()}</AvatarFallback>
    </AvatarRoot>
    <div className="min-w-0 flex-1">
      <OverflowValue value={name} ariaLabel={`查看 ${member.username} 的完整显示名`} className="type-body" />
      <OverflowValue value={`@${member.username}`} ariaLabel={`查看 ${member.username} 的完整用户名`} className="type-meta text-muted" />
    </div>
  </div>
}
