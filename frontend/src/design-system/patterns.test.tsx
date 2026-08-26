import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import * as designSystem from './index'

describe('Quiet Studio shared page patterns', () => {
  it('exports the complete adaptive page vocabulary from the design-system boundary', () => {
    for (const name of [
      'PageFrame',
      'PageHeader',
      'PageIntro',
      'ViewBar',
      'PageSection',
      'CompactSelect',
      'EmptyState',
      'StatusNotice',
      'LoadingState',
      'CalmSkeleton',
      'LoadingReveal',
      'Timeline',
    ]) expect(designSystem).toHaveProperty(name)
  })

  it('defines calm loading and local replacement motion with exact tokens', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')

    expect(css).toContain('--inteliscope-motion-loading: 1400ms')
    expect(css).toContain('--inteliscope-size-page-header: 52px')
    expect(css).toContain('@keyframes inteliscope-skeleton-exit')
    expect(css).toContain('animation: inteliscope-skeleton-exit var(--inteliscope-motion-fast)')
    expect(css).toContain('@keyframes inteliscope-content-reveal')
    expect(css).toContain('translateY(4px)')
    expect(css).toContain('animation: inteliscope-content-reveal 200ms')
    expect(css).toContain('@keyframes quiet-surface-exit')
    expect(css).toContain('animation: quiet-surface-exit var(--inteliscope-motion-deliberate)')
  })

  it('keeps the shared page header transparent and rounded without painting its outer track', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')
    const patterns = readFileSync(resolve(process.cwd(), 'src/design-system/patterns.tsx'), 'utf8')

    expect(css).toContain('--inteliscope-size-page-header: 52px')
    expect(css).toContain('--inteliscope-size-page-header-surface: 44px')
    expect(css).toContain('--inteliscope-inset-page-header-inline: 8px')
    expect(css).toContain('--inteliscope-inset-page-header-block: 4px')
    expect(css).toContain('--inteliscope-radius-page-header: 999px')
    expect(patterns).toContain('h-[var(--inteliscope-size-page-header-surface)]')
    expect(patterns).toContain('bg-surface/75')
    expect(patterns).toContain('backdrop-blur-xl')
    expect(patterns).toContain('rounded-[var(--inteliscope-radius-page-header)]')
    expect(patterns).toContain('data-page-header-appearance="inset"')
    expect(patterns).not.toContain('quiet-page-header-track-fill')
    expect(designSystem.PAGE_HEADER_SIZE_PX).toBe(52)
    expect(css).toContain('[data-page-scroll-region]')
    expect(css).toContain('padding-block-start: var(--inteliscope-size-page-header)')
    expect(css).toContain('scroll-padding-block-start: var(--inteliscope-size-page-header)')
  })
})
