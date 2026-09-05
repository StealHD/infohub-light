import { describe, expect, it } from 'vitest'

import { browseNavigation, managementNavigation, mobilePrimaryNavigation } from './workbenchNavigation'

describe('Agent navigation ownership', () => {
  it('keeps OpenClaw out of Browse while keeping assistant connections in Management', () => {
    expect(browseNavigation.map(({ href }) => href)).toEqual(['/feed', '/saved', '/history'])
    expect(managementNavigation.map(({ href }) => href)).toContain('/subscriptions')
    expect(managementNavigation.map(({ href }) => href)).toContain('/agents')
  })

  it('keeps mobile primary navigation scoped to Inscope', () => {
    expect(mobilePrimaryNavigation.map(({ href }) => href)).toEqual(['/feed', '/saved', '/subscriptions'])
  })
})
