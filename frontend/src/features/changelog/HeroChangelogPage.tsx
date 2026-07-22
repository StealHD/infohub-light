import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Icons, PageFrame } from '../../design-system'
import { changelogMonths, defaultChangelogMonthId, isChangelogMonthId } from './changelogEntries'

function initialMonthId(hash: string) {
  const value = hash.replace(/^#/, '')
  return isChangelogMonthId(value) ? value : defaultChangelogMonthId
}

export function HeroChangelogPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollFrame = useRef<number | undefined>(undefined)
  const [activeMonthId, setActiveMonthId] = useState(() => initialMonthId(location.hash))

  useEffect(() => {
    const monthId = initialMonthId(location.hash)
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(monthId)?.scrollIntoView({ block: 'start' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.hash])

  useEffect(() => () => window.cancelAnimationFrame(scrollFrame.current ?? 0), [])

  function selectMonth(monthId: string) {
    if (!isChangelogMonthId(monthId)) return
    setActiveMonthId(monthId)
    navigate({ pathname: location.pathname, search: location.search, hash: `#${monthId}` })
    document.getElementById(monthId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function syncMonthFromScroll() {
    window.cancelAnimationFrame(scrollFrame.current ?? 0)
    scrollFrame.current = window.requestAnimationFrame(() => {
      const scroll = scrollRef.current
      if (!scroll) return
      const threshold = scroll.getBoundingClientRect().top + 112
      const visible = changelogMonths.reduce((selected, month) => {
        const section = document.getElementById(month.id)
        if (!section) return selected
        return section.getBoundingClientRect().top <= threshold ? month.id : selected
      }, changelogMonths[0].id)
      if (visible === activeMonthId) return
      setActiveMonthId(visible)
      window.history.replaceState(window.history.state, '', `${location.pathname}${location.search}#${visible}`)
    })
  }

  const monthButtons = (surface: 'desktop' | 'compact') => changelogMonths.map((month) => {
    const active = month.id === activeMonthId
    return <button
      key={`${surface}-${month.id}`}
      type="button"
      aria-current={active ? 'location' : undefined}
      className={surface === 'desktop'
        ? `relative min-h-11 w-full rounded-r-lg py-2 pl-6 pr-3 text-left transition-colors duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus ${active ? 'text-foreground before:absolute before:-left-px before:inset-y-1.5 before:w-0.5 before:rounded-full before:bg-accent' : 'text-muted hover:bg-default hover:text-foreground'}`
        : `type-control shrink-0 rounded-full border px-3 py-1.5 transition-colors duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus ${active ? 'border-accent/40 bg-accent/15 text-accent' : 'border-separator text-muted hover:bg-default hover:text-foreground'}`}
      onClick={() => selectMonth(month.id)}
    >{month.label}</button>
  })

  return <div ref={scrollRef} className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto" onScroll={syncMonthFromScroll}>
    <PageFrame width="admin" className="p-4 min-[768px]:p-6">
      <div className="mb-8 flex items-start gap-3 border-b border-separator pb-6">
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent"><Icons.ScrollText size={18} aria-hidden="true" /></span>
        <div>
          <p className="type-card-title">Inteliscope 更新日志</p>
          <p className="type-body mt-1 max-w-2xl text-muted">按时间了解重要功能、交互和可用性变化。</p>
        </div>
      </div>

      <nav aria-label="更新月份" className="quiet-scroll-region sticky top-0 z-10 -mx-4 mb-7 flex gap-2 overflow-x-auto border-y border-separator bg-background/95 px-4 py-3 backdrop-blur min-[1080px]:hidden">
        {monthButtons('compact')}
      </nav>

      <div className="grid min-w-0 gap-12 min-[1080px]:grid-cols-[minmax(0,1fr)_190px]">
        <div className="min-w-0 max-w-3xl">
          {changelogMonths.map((month) => <section
            key={month.id}
            id={month.id}
            aria-labelledby={`${month.id}-heading`}
            className="scroll-mt-24 pb-14 last:pb-6"
          >
            <h2 id={`${month.id}-heading`} className="type-section-title mb-7">{month.label}</h2>
            <div className="grid gap-10">
              {month.entries.map((entry, index) => <article key={`${entry.date}-${entry.title}`} className={index ? 'border-t border-separator pt-9' : ''}>
                <time className="type-meta text-muted" dateTime={entry.date}>{entry.date}</time>
                <h3 className="type-page-title mt-2">{entry.title}</h3>
                <p className="type-body mt-2 text-muted">{entry.summary}</p>
                <div className="mt-5 grid gap-4">
                  {entry.items.map((item) => <div key={item.title} className="grid gap-1 sm:grid-cols-[136px_minmax(0,1fr)] sm:gap-5">
                    <strong className="type-control">{item.title}</strong>
                    <p className="type-body text-muted">{item.description}</p>
                  </div>)}
                </div>
              </article>)}
            </div>
          </section>)}
        </div>

        <aside className="hidden min-[1080px]:block" aria-label="更新日志时间线">
          <nav aria-label="更新月份时间线" className="sticky top-6 border-l border-separator py-1">
            {monthButtons('desktop')}
          </nav>
        </aside>
      </div>
    </PageFrame>
  </div>
}
