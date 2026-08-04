import { describe, expect, it } from 'vitest'

import {
  settingsSectionFromHash,
  settingsSectionsForRole,
} from './settingsSections'

describe('settingsSections', () => {
  it('shows eight sections to administrators and four to members or viewers', () => {
    expect(settingsSectionsForRole('owner')).toHaveLength(8)
    expect(settingsSectionsForRole('admin')).toHaveLength(8)
    expect(settingsSectionsForRole('member')).toHaveLength(4)
    expect(settingsSectionsForRole('viewer')).toHaveLength(4)
    expect(settingsSectionFromHash('#settings-storage', 'admin')?.label).toBe('存储与归档')
    expect(settingsSectionFromHash('#settings-storage', 'member')).toBeNull()
  })

  it('rejects an unknown or role-inaccessible settings hash', () => {
    expect(settingsSectionFromHash('#settings-secrets', 'owner')?.label).toBe('密钥')
    expect(settingsSectionFromHash('#settings-secrets', 'member')).toBeNull()
    expect(settingsSectionFromHash('#settings-unknown', 'owner')).toBeNull()
  })
})
