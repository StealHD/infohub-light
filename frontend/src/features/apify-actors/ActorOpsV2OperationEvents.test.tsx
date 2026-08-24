import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { AppOutletContext } from '../../app/AppContext'
import { ActorOpsV2OperationEvents } from './ActorOpsV2OperationEvents'

function renderEvents(events: Array<Record<string, unknown>>, jobId?: string) {
  const actorOpsV2Events = vi.fn().mockResolvedValue({ schema_version: 3, availability: 'available', events, returned: events.length, truncated: false, window: { from: '2026-08-24T00:00:00Z', to: '2026-08-25T00:00:00Z' } })
  const context = { api: { actorOpsV2Events }, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } } as unknown as AppOutletContext
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<ActorOpsV2OperationEvents jobId={jobId} />} /></Route></Routes></MemoryRouter></QueryClientProvider>)
  return actorOpsV2Events as ReturnType<typeof vi.fn>
}

describe('ActorOpsV2OperationEvents', () => {
  it('maps all current management operations and keeps unknown history explicit', async () => {
    const actions = [
      'actorops_v2_candidate_promote', 'actorops_v2_binding_verify', 'actorops_v2_binding_enable', 'actorops_v2_discovery_create', 'actorops_v2_metadata_refresh', 'actorops_v2_price_cap',
      'actorops_v2_replacement_preview', 'actorops_v2_replacement_authorize', 'actorops_v2_replacement_apply', 'actorops_v2_replacement_cancel', 'actorops_v2_workspace_maintenance_policy_update', 'actorops_v2_route_maintenance_policy_update', 'actorops_v2_future_action',
    ]
    renderEvents(actions.map((action, index) => ({ event_id: `event-${index}`, timestamp: '2026-08-24T17:00:00Z', action, outcome: 'succeeded', level: 'info', route: '/api/raw-target', source_id: 'source-private' })))

    for (const label of ['已调整主用 Actor', '已核验来源 Binding', '已启用来源 Binding', '已创建候选发现任务', '已刷新商城信息', '已更新 Route 费用上限', '已创建替换预览', '已授权替换计划', '已应用替换计划', '已取消替换计划', '已更新工作区维护策略', '已更新 Route 维护策略', '未识别管理操作']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.queryByText('/api/raw-target')).not.toBeInTheDocument()
    expect(screen.queryByText('source-private')).not.toBeInTheDocument()
  })

  it('expands only safe operation details and scopes a deep-linked job query', async () => {
    const actorOpsV2Events = renderEvents([{ event_id: 'unknown', timestamp: '2026-08-24T17:00:00Z', action: 'actorops_v2_future_action', outcome: 'failed', level: 'error', phase: 'reconcile', changed_fields: ['actorops_v2_future_action'], counts: { processed: 2 }, final_cost_usd: 0.05, error_code: 'actorops_v2_safe_error', method: 'POST', status_code: 409, route: '/api/private-target' }], 'job-1')

    await waitFor(() => expect(actorOpsV2Events).toHaveBeenCalledWith({ job_id: 'job-1' }, expect.anything()))
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看详情' }))
    for (const label of ['阶段', '变更字段', '数量', '最终费用', '错误码', '请求结果', '安全 action code']) expect(screen.getByText(label)).toBeInTheDocument()
    expect(screen.getByText('actorops_v2_future_action')).toBeInTheDocument()
    expect(screen.queryByText('/api/private-target')).not.toBeInTheDocument()
  })
})
