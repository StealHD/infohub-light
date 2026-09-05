import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { User } from '../../api/types'
import { AvatarFallback, AvatarRoot, Button, Icons, Popover, Separator } from '../../design-system'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import { settingsReturnStateForLocation } from '../settings/settingsReturnState'

const roleLabel = { owner: '所有者', admin: '管理员', member: '成员', viewer: '只读成员' } as const

export function WorkspaceAccountMenu({ user, onLogout, expanded = true, variant = 'feed' }: {
  user: User; onLogout: () => void; expanded?: boolean; variant?: 'feed' | 'agent'
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const displayName = user.display_name || user.username
  return (
      <Popover isOpen={accountMenuOpen} onOpenChange={setAccountMenuOpen}>
        <Popover.Trigger aria-label="打开账户菜单" title={expanded ? undefined : '账户'} className={variant === "agent" ? "flex h-12 min-w-0 w-full items-center gap-2 rounded-xl p-1.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus" : "sidebar-account-trigger flex h-12 min-w-0 w-[175px] items-center gap-2 rounded-xl p-1.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus"}>
          <span data-sidebar-account-avatar className="sidebar-account-avatar flex size-8 shrink-0 items-center justify-center"><AvatarRoot className="size-8"><AvatarFallback>{displayName.slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot></span>
          <span data-sidebar-account-copy className="min-w-0 flex-1" aria-hidden={!expanded}><span className="type-control block truncate">{displayName}</span><span className="type-label block truncate text-muted">{roleLabel[user.role]}</span></span>
        </Popover.Trigger>
        <Popover.Content data-account-menu-surface data-sidebar-menu-direction="up" placement="top start" offset={8} containerPadding={12} className="z-50 w-52 p-0">
          <Popover.Dialog aria-label="账户菜单" className="p-2">
            <div className="px-2 py-2"><strong className="type-control block truncate">{displayName}</strong><span className="type-meta text-muted">{user.username} · {roleLabel[user.role]}</span></div>
            <Separator className="my-1" />
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/users') }}><Icons.Users size={16} aria-hidden="true" />账户与成员</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/settings', { state: settingsReturnStateForLocation(location) }) }}><Icons.Settings size={16} aria-hidden="true" />设置</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/manual') }}><Icons.BookOpen size={16} aria-hidden="true" />操作手册</Button>
            <Button variant="ghost" className="w-full justify-start" onPress={() => { setAccountMenuOpen(false); navigate('/changelog') }}><Icons.ScrollText size={16} aria-hidden="true" />更新日志</Button>
            <a href={PRODUCT_RELEASES_URL} target="_blank" rel="noopener noreferrer" className="type-control flex min-h-9 w-full items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus" onClick={() => setAccountMenuOpen(false)}><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink className="ml-auto" size={13} aria-hidden="true" /></a>
            <Separator className="my-1" />
            <Button variant="ghost" className="w-full justify-start text-danger" aria-label="退出登录" onPress={onLogout}><Icons.LogOut size={16} aria-hidden="true" />退出登录</Button>
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
  )
}
