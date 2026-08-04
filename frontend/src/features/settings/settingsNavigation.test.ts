import { describe, expect, it } from 'vitest'

import {
  activeSettingsNavigationId,
  settingsDestinationFromLegacyHash,
  settingsNavigationForRole,
  settingsWorkspaceTitle,
} from './settingsNavigation'

describe('settingsNavigation', () => {
  it('exposes the requested groups and scopes developer settings to administrators', () => {
    const ownerItems = settingsNavigationForRole('owner').flatMap((group) => group.items)
    const memberItems = settingsNavigationForRole('member').flatMap((group) => group.items)

    expect(ownerItems.map((item) => item.label)).toEqual(['概览', '来源', '获取与主题', '已忽略内容', 'AI', '通知', '外观', '密钥', 'ActorOps', '高级'])
    expect(memberItems.map((item) => item.label)).toEqual(['概览', '来源', '已忽略内容', 'AI', '通知', '外观'])
    expect(ownerItems.find((item) => item.id === 'sources')).toMatchObject({ href: '/subscriptions', bridge: true })
  })

  it('maps native and legacy locations to a stable sidebar selection and title', () => {
    expect(activeSettingsNavigationId('/settings/notifications', '')).toBe('notifications')
    expect(activeSettingsNavigationId('/settings/appearance', '')).toBe('appearance')
    expect(activeSettingsNavigationId('/settings/ai', '')).toBe('ai')
    expect(activeSettingsNavigationId('/settings/fetching', '')).toBe('fetching')
    expect(activeSettingsNavigationId('/settings/ignored', '')).toBe('ignored')
    expect(activeSettingsNavigationId('/settings/secrets', '')).toBe('secrets')
    expect(activeSettingsNavigationId('/settings/actorops', '')).toBe('actorops')
    expect(activeSettingsNavigationId('/settings/legacy', '#settings-storage')).toBe('advanced')
    expect(activeSettingsNavigationId('/settings/legacy', '#settings-ai')).toBe('overview')
    expect(activeSettingsNavigationId('/settings/legacy', '')).toBe('advanced')
    expect(settingsWorkspaceTitle('/settings/secrets', '')).toBe('密钥')
    expect(settingsWorkspaceTitle('/settings/ignored', '')).toBe('已忽略内容')
    expect(settingsWorkspaceTitle('/settings/fetching', '')).toBe('获取与主题')
  })

  it('keeps old hashes compatible without exposing administrator pages to members', () => {
    expect(settingsDestinationFromLegacyHash('#settings-about', 'member')).toBe('/settings')
    expect(settingsDestinationFromLegacyHash('#settings-notifications', 'member')).toBe('/settings/notifications')
    expect(settingsDestinationFromLegacyHash('#settings-ai', 'member')).toBe('/settings/ai')
    expect(settingsDestinationFromLegacyHash('#settings-ignored', 'member')).toBe('/settings/ignored')
    expect(settingsDestinationFromLegacyHash('#settings-secrets', 'owner')).toBe('/settings/secrets')
    expect(settingsDestinationFromLegacyHash('#settings-secrets', 'member')).toBe('/settings')
    expect(settingsDestinationFromLegacyHash('#settings-fetching', 'owner')).toBe('/settings/fetching')
    expect(settingsDestinationFromLegacyHash('#settings-fetching', 'member')).toBe('/settings')
    expect(settingsDestinationFromLegacyHash('#settings-actorops', 'owner')).toBe('/settings/actorops')
    expect(settingsDestinationFromLegacyHash('#settings-storage', 'owner')).toBe('/settings/legacy#settings-storage')
    expect(settingsDestinationFromLegacyHash('#settings-storage', 'member')).toBe('/settings')
    expect(settingsDestinationFromLegacyHash('#settings-unknown', 'owner')).toBe('/settings')
  })
})
