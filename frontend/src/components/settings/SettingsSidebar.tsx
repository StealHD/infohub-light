import { NavLink, useLocation } from 'react-router-dom'

import type { UserRole } from '../../api/types'
import { Button, Icons } from '../../design-system'
import {
  activeSettingsNavigationId,
  settingsNavigationForRole,
} from '../../features/settings/settingsNavigation'

export function SettingsSidebar({ role, returnTo, onBack, onNavigate, className = '' }: {
  role: UserRole
  returnTo: string
  onBack: () => void
  onNavigate?: () => void
  className?: string
}) {
  const location = useLocation()
  const activeId = activeSettingsNavigationId(location.pathname, location.hash)
  const groups = settingsNavigationForRole(role)

  return <div data-settings-sidebar className={`flex h-full min-h-0 flex-col bg-surface ${className}`}>
    <div className="flex h-[52px] shrink-0 items-center border-b border-separator px-3">
      <Button
        variant="ghost"
        className="min-h-9 w-full justify-start gap-2 px-2 text-muted hover:text-foreground"
        onPress={onBack}
      ><Icons.ArrowLeft size={17} aria-hidden="true" />返回应用</Button>
    </div>
    <nav aria-label="设置导航" className="quiet-scroll-region min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-3 py-4">
      {groups.map((group, groupIndex) => <section
        key={group.id}
        aria-labelledby={group.label ? `settings-nav-${group.id}` : undefined}
        className={groupIndex > 0 ? 'mt-5' : ''}
      >
        {group.label && <h2 id={`settings-nav-${group.id}`} className="type-meta mb-1.5 px-2 text-muted">{group.label}</h2>}
        <div className="grid gap-1">
          {group.items.map(({ id, label, href, icon: Icon, bridge }) => <NavLink
            key={id}
            to={href}
            state={bridge ? undefined : { settingsReturnTo: returnTo }}
            aria-current={activeId === id ? 'page' : undefined}
            onClick={onNavigate}
            className="type-control flex min-h-10 items-center gap-3 rounded-xl px-2.5 text-muted hover:bg-default/70 hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus aria-[current=page]:bg-default aria-[current=page]:text-foreground"
          >
            <Icon size={18} strokeWidth={1.7} aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {bridge && <Icons.ExternalLink size={13} aria-hidden="true" />}
          </NavLink>)}
        </div>
      </section>)}
    </nav>
  </div>
}
