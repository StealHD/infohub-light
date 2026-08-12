import { describe, expect, it } from 'vitest'

import { settingsSectionsForRole } from './settingsSections'

describe('settingsSections', () => {
  it('shows eight sections to administrators and four to members or viewers', () => {
    expect(settingsSectionsForRole('owner')).toHaveLength(8)
    expect(settingsSectionsForRole('admin')).toHaveLength(8)
    expect(settingsSectionsForRole('member')).toHaveLength(4)
    expect(settingsSectionsForRole('viewer')).toHaveLength(4)
  })
})
