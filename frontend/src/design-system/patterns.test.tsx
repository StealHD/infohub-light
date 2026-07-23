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
    ]) expect(designSystem).toHaveProperty(name)
  })

  it('defines calm loading and local replacement motion with exact tokens', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')

    expect(css).toContain('--inteliscope-motion-loading: 1400ms')
    expect(css).toContain('@keyframes inteliscope-skeleton-exit')
    expect(css).toContain('animation: inteliscope-skeleton-exit var(--inteliscope-motion-fast)')
    expect(css).toContain('@keyframes inteliscope-content-reveal')
    expect(css).toContain('translateY(4px)')
    expect(css).toContain('animation: inteliscope-content-reveal 200ms')
    expect(css).toContain('@keyframes quiet-surface-exit')
    expect(css).toContain('animation: quiet-surface-exit var(--inteliscope-motion-deliberate)')
  })
})
