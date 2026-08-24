import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { AppOutletContext } from '../../app/AppContext'
import { ActorOpsAlertIncidentList } from './ActorOpsAlerts'

describe('ActorOpsAlertIncidentList', () => {
  it('gives an unknown start a reconciliation link and no retry or manual close action', async () => {
    const context = {
      api: { apifyActorAlertIncidents: vi.fn().mockResolvedValue({ schema_version: 3, incidents: [{ schema_version: 3, id: 'incident-1', route: 'x/profile', event_type: 'start_outcome_unknown', severity: 'critical', status: 'open', actor_name: null, active_actor_name: null, reason_code: 'ignored', opened_at: '2026-08-24T16:00:00Z', last_seen_at: '2026-08-24T17:00:00Z', resolved_at: null, deliveries: [], delivery_status: 'pending', delivery_error_code: null }] }) },
      user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
    } as unknown as AppOutletContext
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<ActorOpsAlertIncidentList />} /></Route></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByText('无法确认 Actor 是否已启动。')).toBeInTheDocument()
    expect(screen.getByText(/为避免重复扣费/)).toBeInTheDocument()
    expect(screen.getByText(/不要重试/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '打开 Apify 运行记录' })).toHaveAttribute('href', 'https://console.apify.com/actors/runs')
    expect(screen.getByRole('button', { name: '刷新日志' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /重试|关闭|已处理/ })).not.toBeInTheDocument()
  })
})
