import { describe, expect, it } from 'vitest'

import { settingsSectionFromHash, settingsSectionsForRole } from './settingsSections'

describe('settingsSections', () => {
  it('shows six sections to administrators and four to members or viewers', () => {
    expect(settingsSectionsForRole('owner')).toHaveLength(6)
    expect(settingsSectionsForRole('admin')).toHaveLength(6)
    expect(settingsSectionsForRole('member')).toHaveLength(4)
    expect(settingsSectionsForRole('viewer')).toHaveLength(4)
  })

  it('rejects an unknown or role-inaccessible settings hash', () => {
    expect(settingsSectionFromHash('#settings-secrets', 'owner')?.label).toBe('密钥')
    expect(settingsSectionFromHash('#settings-secrets', 'member')).toBeNull()
    expect(settingsSectionFromHash('#settings-unknown', 'owner')).toBeNull()
  })
})
