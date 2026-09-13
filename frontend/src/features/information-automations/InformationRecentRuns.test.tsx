import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from '../../design-system'
import { InformationRecentRuns } from './InformationRecentRuns'

const api = { informationRuns: vi.fn() }
vi.mock('./useInformationContext', () => ({ useInformationContext: () => ({ api, userId: 'alice' }) }))

function renderRecent(onViewAll = vi.fn()) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={cache}><DesignSystemProvider><InformationRecentRuns ruleId="rule" onViewAll={onViewAll} /></DesignSystemProvider></QueryClientProvider></MemoryRouter>)
  return onViewAll
}

it('shows only the three latest real runs and never reports an unverified send as success', async () => {
  api.informationRuns.mockResolvedValue({ items: [0, 1, 2, 3].map((index) => ({
    id: `run-${index}`, version: 1, status: index === 0 ? 'matched' : 'not_matched', notification_status: 'sent', receipt: index === 0 ? null : { channel: 'telegram', verification: 'verified' },
    reason: null, evidence: [], created_at: `2026-09-0${4 - index}T08:00:00Z`, updated_at: '2026-09-04T08:00:00Z',
  })), has_more: false, next_offset: null })
  const onViewAll = renderRecent()
  const list = await screen.findByRole('list', { name: '最近三次运行' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(3)
  expect(within(list).getByText(/命中 · 没有可验证回执/)).toBeVisible()
  await userEvent.setup().click(screen.getByRole('button', { name: '查看全部' }))
  expect(onViewAll).toHaveBeenCalledOnce()
})

it('keeps empty and failed run reads actionable', async () => {
  api.informationRuns.mockResolvedValueOnce({ items: [], has_more: false, next_offset: null })
  renderRecent()
  expect(await screen.findByText('暂无运行。启动后只处理新增内容。')).toBeVisible()
  api.informationRuns.mockRejectedValueOnce(new Error('offline'))
  renderRecent()
  expect(await screen.findByRole('alert')).toHaveTextContent('最近运行读取失败，请在运行记录中重试。')
})
