import { describe, expect, it } from 'vitest'

import {
  routeProductNames,
  routeProfileId,
  routeProfileOrder,
  routeWorkflowPresentation,
  taskTabs,
} from './actorOpsPresentation'

describe('ActorOps presentation model', () => {
  it('keeps the supported task and route order stable', () => {
    expect([...taskTabs]).toEqual(['pool', 'sources', 'operations'])
    expect(routeProfileOrder).toEqual([
      'x/profile/items',
      'instagram/profile/items',
      'youtube/channel/items',
    ])
    expect(routeProductNames['youtube/channel/items']).toEqual({
      label: 'YouTube 频道视频',
      description: '原生优先 · Actor 故障回退',
    })
  })

  it('maps route identity without exposing source-specific state', () => {
    expect(routeProfileId({
      platform: 'instagram',
      target_type: 'profile',
      capability: 'items',
    })).toBe('instagram/profile/items')
  })

  it('preserves the standard and one-actor workflow variants', () => {
    expect(routeWorkflowPresentation('setup_discovery_required', 2)).toMatchObject({
      title: '尚未建立 Actor 主备',
      action: 'start_discovery',
      cta: '开始建立主备',
    })
    expect(routeWorkflowPresentation('setup_discovery_required', 1)).toMatchObject({
      title: '尚未建立 Actor fallback',
      action: 'start_discovery',
      cta: '开始建立 fallback',
    })
  })

  it('fails closed to a refresh action for an unknown workflow', () => {
    expect(routeWorkflowPresentation('future_unmapped_state', 3)).toEqual({
      title: '状态需要刷新',
      description: '当前没有可安全执行的操作。刷新后仍会以服务端状态为准。',
      status: '需要核对',
      tone: 'warning',
      action: 'refresh',
      cta: '刷新状态',
    })
  })
})
