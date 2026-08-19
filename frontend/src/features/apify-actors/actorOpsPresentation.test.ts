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
      description: 'Actor 主抓取',
    })
  })

  it('maps route identity without exposing source-specific state', () => {
    expect(routeProfileId({
      platform: 'instagram',
      target_type: 'profile',
      capability: 'items',
    })).toBe('instagram/profile/items')
  })

  it('keeps standard discovery copy independent of stale minimum counts', () => {
    expect(routeWorkflowPresentation('setup_discovery_required', 2)).toMatchObject({
      title: '尚未建立 Actor 主备',
      action: 'start_discovery',
      cta: '开始建立主备',
    })
    expect(routeWorkflowPresentation('setup_discovery_required', 1)).toMatchObject({
      title: '尚未建立 Actor 主备',
      action: 'start_discovery',
      cta: '开始建立主备',
    })
  })

  it('keeps a persisted slot replan distinct from a legacy upgrade', () => {
    expect(routeWorkflowPresentation(
      'replace_slot_candidate_selection_required', 3, 'primary',
    )).toMatchObject({
      title: '选择主用 Actor 的替换候选',
      action: 'select_candidates',
      cta: '选择替换主用 Actor',
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
