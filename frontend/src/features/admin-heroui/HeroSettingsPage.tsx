import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import { PageFrame } from '../../design-system'
import { HeroApifyActorRouteSettings } from '../apify-actors/HeroApifyActorRouteSettings'
import { AdminPageHeader, AdminSection, HeroSelect } from './HeroAdminControls'
import { StorageArchiveSettings } from './StorageArchiveSettings'
import { legacySettingsSectionFromHash, legacySettingsSectionsForRole } from './settingsSections'

export function HeroSettingsPage() {
  const { user } = useAppContext()
  const navigate = useNavigate()
  const location = useLocation()
  const defaultSection = 'settings-actorops'
  const [activeSection, setActiveSection] = useState<string>(
    () => legacySettingsSectionFromHash(location.hash, user.role)?.id ?? defaultSection,
  )
  const [activatedSections, setActivatedSections] = useState<Set<string>>(
    () => new Set([legacySettingsSectionFromHash(location.hash, user.role)?.id ?? defaultSection]),
  )
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const activeSectionRef = useRef(activeSection)
  const scrollActivationFrameRef = useRef<number | undefined>(undefined)
  const scrollUnlockFrameRef = useRef<number | undefined>(undefined)
  const scrollActivationPendingRef = useRef(false)
  const lastScrollTopRef = useRef(0)
  const lastTouchYRef = useRef<number | null>(null)
  const explicitSectionNavigationRef = useRef(Boolean(legacySettingsSectionFromHash(location.hash, user.role)))
  const sectionOptions = useMemo(() => legacySettingsSectionsForRole(user.role), [user.role])

  const activateSection = useCallback((id: string) => {
    activeSectionRef.current = id
    setActiveSection(id)
    setActivatedSections((current) => {
      if (current.has(id)) return current
      const next = new Set(current)
      next.add(id)
      return next
    })
  }, [])

  const scheduleAdjacentSectionActivation = useCallback((direction: -1 | 1) => {
    const root = scrollContainerRef.current
    if (!root || scrollActivationPendingRef.current) return
    const activeIndex = sectionOptions.findIndex((section) => section.id === activeSectionRef.current)
    const candidate = sectionOptions[activeIndex + direction]
    if (!candidate) return
    const candidateElement = document.getElementById(candidate.id)
    if (!candidateElement) return
    const rootRect = root.getBoundingClientRect()
    const candidateRect = candidateElement.getBoundingClientRect()
    const revealInset = Math.min(64, Math.max(24, rootRect.height / 8))
    if (candidateRect.bottom < rootRect.top + revealInset || candidateRect.top > rootRect.bottom - revealInset) return

    scrollActivationPendingRef.current = true
    window.cancelAnimationFrame(scrollActivationFrameRef.current ?? 0)
    scrollActivationFrameRef.current = window.requestAnimationFrame(() => {
      activateSection(candidate.id)
      window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}#${candidate.id}`)
      window.cancelAnimationFrame(scrollUnlockFrameRef.current ?? 0)
      scrollUnlockFrameRef.current = window.requestAnimationFrame(() => {
        lastScrollTopRef.current = root.scrollTop
        scrollActivationPendingRef.current = false
      })
    })
  }, [activateSection, sectionOptions])

  useEffect(() => {
    const section = legacySettingsSectionFromHash(location.hash, user.role)
    if (!section) return
    explicitSectionNavigationRef.current = true
    const frame = window.requestAnimationFrame(() => {
      activateSection(section.id)
      const target = document.getElementById(section.id)
      target?.scrollIntoView?.({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
      target?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activateSection, location.hash, user.role])

  useEffect(() => {
    const root = scrollContainerRef.current
    if (!root) return
    lastScrollTopRef.current = root.scrollTop
    const nestedScrollConsumes = (target: EventTarget | null, direction: -1 | 1) => {
      let element = target instanceof HTMLElement ? target : null
      while (element && element !== root) {
        const overflowY = window.getComputedStyle(element).overflowY
        if (['auto', 'scroll'].includes(overflowY) && element.scrollHeight > element.clientHeight && ((direction > 0 && element.scrollTop + element.clientHeight < element.scrollHeight - 1) || (direction < 0 && element.scrollTop > 1))) return true
        element = element.parentElement
      }
      return false
    }
    const activateFromScroll = () => {
      const nextScrollTop = root.scrollTop
      const delta = nextScrollTop - lastScrollTopRef.current
      lastScrollTopRef.current = nextScrollTop
      if (!explicitSectionNavigationRef.current && Math.abs(delta) >= 1) scheduleAdjacentSectionActivation(delta > 0 ? 1 : -1)
    }
    const activateFromWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) < 1 || nestedScrollConsumes(event.target, event.deltaY > 0 ? 1 : -1)) return
      explicitSectionNavigationRef.current = false
      scheduleAdjacentSectionActivation(event.deltaY > 0 ? 1 : -1)
    }
    const rememberTouch = (event: TouchEvent) => {
      lastTouchYRef.current = event.touches[0]?.clientY ?? null
      explicitSectionNavigationRef.current = false
    }
    const activateFromTouch = (event: TouchEvent) => {
      const currentY = event.touches[0]?.clientY
      const previousY = lastTouchYRef.current
      if (currentY === undefined || previousY === null) return
      lastTouchYRef.current = currentY
      const delta = previousY - currentY
      if (Math.abs(delta) < 4 || nestedScrollConsumes(event.target, delta > 0 ? 1 : -1)) return
      scheduleAdjacentSectionActivation(delta > 0 ? 1 : -1)
    }
    const activateFromKeyboard = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && event.target.closest('button, a, input, textarea, select, [contenteditable="true"], [role="combobox"], [role="listbox"], [role="menu"], [role="slider"], [role="spinbutton"]')) return
      if (['ArrowDown', 'PageDown', 'End'].includes(event.key) || (event.key === ' ' && !event.shiftKey)) {
        explicitSectionNavigationRef.current = false
        scheduleAdjacentSectionActivation(1)
      } else if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey)) {
        explicitSectionNavigationRef.current = false
        scheduleAdjacentSectionActivation(-1)
      }
    }
    root.addEventListener('scroll', activateFromScroll, { passive: true })
    root.addEventListener('wheel', activateFromWheel, { passive: true })
    root.addEventListener('touchstart', rememberTouch, { passive: true })
    root.addEventListener('touchmove', activateFromTouch, { passive: true })
    root.addEventListener('keydown', activateFromKeyboard)
    return () => {
      root.removeEventListener('scroll', activateFromScroll)
      root.removeEventListener('wheel', activateFromWheel)
      root.removeEventListener('touchstart', rememberTouch)
      root.removeEventListener('touchmove', activateFromTouch)
      root.removeEventListener('keydown', activateFromKeyboard)
    }
  }, [scheduleAdjacentSectionActivation])

  useEffect(() => () => {
    window.cancelAnimationFrame(scrollActivationFrameRef.current ?? 0)
    window.cancelAnimationFrame(scrollUnlockFrameRef.current ?? 0)
    scrollActivationPendingRef.current = false
  }, [])

  function jumpToSection(id: string) {
    if (!sectionOptions.some((section) => section.id === id)) return
    activateSection(id)
    navigate({ pathname: location.pathname, search: location.search, hash: `#${id}` })
  }

  return <div ref={scrollContainerRef} data-settings-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-5 p-4 min-[768px]:p-6">
      <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
      <div data-mobile-settings-selector className="min-[768px]:pointer-fine:hidden"><HeroSelect label="设置区域" value={activeSection} onChange={jumpToSection} options={[...sectionOptions]} className="w-full" /></div>
      <div className="grid min-w-0 gap-5">
        <AdminSection id="settings-actorops" title="ActorOps" description="管理 Actor 路由、运行告警和最近事件。">
          {activatedSections.has('settings-actorops') && <HeroApifyActorRouteSettings queryEnabled={activeSection === 'settings-actorops'} />}
        </AdminSection>
        <AdminSection id="settings-storage" title="存储与归档" description="预演工作区清理、90 日冷归档与恢复；所有操作均先核对候选指纹并记录审计。">
          {activatedSections.has('settings-storage') && <StorageArchiveSettings queryEnabled={activeSection === 'settings-storage'} />}
        </AdminSection>
      </div>
    </PageFrame>
  </div>
}
