import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Icons, Link, PageFrame } from '../../design-system'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import {
  defaultManualSectionId,
  isManualSectionId,
  manualReview,
  manualSections,
} from './manualContent'

function initialSectionId(hash: string) {
  const value = hash.replace(/^#/, '')
  return isManualSectionId(value) ? value : defaultManualSectionId
}

export function HeroManualPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollFrame = useRef<number | undefined>(undefined)
  const [activeSectionId, setActiveSectionId] = useState(() => initialSectionId(location.hash))

  useEffect(() => {
    if (!location.hash) {
      scrollRef.current?.scrollTo({ top: 0 })
      return
    }
    const sectionId = initialSectionId(location.hash)
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(sectionId)?.scrollIntoView({ block: 'start' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.hash])

  useEffect(() => () => window.cancelAnimationFrame(scrollFrame.current ?? 0), [])

  function selectSection(sectionId: string) {
    if (!isManualSectionId(sectionId)) return
    setActiveSectionId(sectionId)
    navigate({ pathname: location.pathname, search: location.search, hash: `#${sectionId}` })
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function syncSectionFromScroll() {
    window.cancelAnimationFrame(scrollFrame.current ?? 0)
    scrollFrame.current = window.requestAnimationFrame(() => {
      const scroll = scrollRef.current
      if (!scroll) return
      const threshold = scroll.getBoundingClientRect().top + 112
      const visible = manualSections.reduce((selected, section) => {
        const element = document.getElementById(section.id)
        if (!element) return selected
        return element.getBoundingClientRect().top <= threshold ? section.id : selected
      }, manualSections[0].id)
      if (visible === activeSectionId) return
      setActiveSectionId(visible)
      window.history.replaceState(window.history.state, '', `${location.pathname}${location.search}#${visible}`)
    })
  }

  const sectionButtons = (surface: 'desktop' | 'compact') => manualSections.map((section) => {
    const active = section.id === activeSectionId
    return <button
      key={`${surface}-${section.id}`}
      type="button"
      aria-current={active ? 'location' : undefined}
      className={surface === 'desktop'
        ? `relative min-h-11 w-full rounded-r-lg py-2 pl-6 pr-3 text-left transition-colors duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus ${active ? 'text-foreground before:absolute before:-left-px before:inset-y-1.5 before:w-0.5 before:rounded-full before:bg-accent' : 'text-muted hover:bg-default hover:text-foreground'}`
        : `type-control shrink-0 rounded-full border px-3 py-1.5 transition-colors duration-[var(--inteliscope-motion-standard)] focus-visible:outline-2 focus-visible:outline-focus ${active ? 'border-accent/40 bg-accent/15 text-accent' : 'border-separator text-muted hover:bg-default hover:text-foreground'}`}
      onClick={() => selectSection(section.id)}
    >{section.label}</button>
  })

  return <div ref={scrollRef} className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto" onScroll={syncSectionFromScroll}>
    <PageFrame width="admin" className="p-4 min-[768px]:p-6">
      <div className="mb-8 flex flex-col gap-4 border-b border-separator pb-6 min-[680px]:flex-row min-[680px]:items-start min-[680px]:justify-between">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent"><Icons.BookOpen size={18} aria-hidden="true" /></span>
          <div>
            <p className="type-card-title">Inteliscope 操作手册</p>
            <p className="type-body mt-1 max-w-2xl text-muted">按实际页面路径完成订阅、阅读、Agent 连接和账户管理。</p>
            <p className="type-meta mt-2 text-muted">
              最后复核：<time dateTime={manualReview.reviewedAt}>{manualReview.reviewedAt}</time>
              <span aria-hidden="true"> · </span>{manualReview.change}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Link href="/changelog" className="type-control inline-flex min-h-9 items-center gap-2 rounded-xl border border-separator px-3 text-muted hover:bg-default hover:text-foreground">
            <Icons.ScrollText size={15} aria-hidden="true" />更新日志
          </Link>
          <a
            href={PRODUCT_RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="type-control inline-flex min-h-9 items-center gap-2 rounded-xl border border-separator px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
          >
            <Icons.Rocket size={15} aria-hidden="true" />Release 发布页<Icons.ExternalLink size={13} aria-hidden="true" />
          </a>
        </div>
      </div>

      <div className="type-body mb-7 rounded-2xl border border-separator bg-surface-secondary p-4 text-muted">
        每次产品代码合并都由 Test Gate 检查本手册与更新日志是否同步复核；缺少任一项时，合并检查会失败。
      </div>

      <nav aria-label="手册章节" className="quiet-scroll-region sticky top-0 z-10 -mx-4 mb-7 flex gap-2 overflow-x-auto border-y border-separator bg-background/95 px-4 py-3 backdrop-blur min-[1080px]:hidden">
        {sectionButtons('compact')}
      </nav>

      <div className="grid min-w-0 gap-12 min-[1080px]:grid-cols-[minmax(0,1fr)_190px]">
        <div className="min-w-0 max-w-3xl">
          {manualSections.map((section) => <section
            key={section.id}
            id={section.id}
            aria-labelledby={`${section.id}-heading`}
            className="scroll-mt-24 border-b border-separator pb-12 pt-2 first:pt-0 last:border-b-0 last:pb-6"
          >
            <h2 id={`${section.id}-heading`} className="type-section-title">{section.label}</h2>
            <p className="type-body mt-2 text-muted">{section.summary}</p>
            <ol className="mt-6 grid gap-5">
              {section.steps.map((step, index) => <li key={step.title} className="grid gap-3 sm:grid-cols-[32px_minmax(0,1fr)]">
                <span className="type-label flex size-8 items-center justify-center rounded-full bg-default text-muted" aria-hidden="true">{index + 1}</span>
                <div>
                  <h3 className="type-page-title">{step.title}</h3>
                  <p className="type-body mt-1 text-muted">{step.description}</p>
                  {step.href && step.linkLabel && <Link href={step.href} className="type-control mt-2 inline-flex items-center gap-1 text-accent">
                    {step.linkLabel}<Icons.ArrowRight size={14} aria-hidden="true" />
                  </Link>}
                </div>
              </li>)}
            </ol>
          </section>)}
        </div>

        <aside className="hidden min-[1080px]:block" aria-label="操作手册目录">
          <nav aria-label="手册章节目录" className="sticky top-6 border-l border-separator py-1">
            {sectionButtons('desktop')}
          </nav>
        </aside>
      </div>
    </PageFrame>
  </div>
}
