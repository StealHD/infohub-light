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
    ]) expect(designSystem).toHaveProperty(name)
  })
})
