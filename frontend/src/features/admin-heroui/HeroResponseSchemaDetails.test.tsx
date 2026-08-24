import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { Job } from '../../api/types'
import { HeroResponseSchemaDetails } from './HeroResponseSchemaDetails'

describe('HeroResponseSchemaDetails', () => {
  it('presents safe schema states behind a softly controlled disclosure without raw values', async () => {
    const browser = userEvent.setup()
    const job: Job = {
      id: 'schema-job', user_id: 'user-1', job_type: 'source_fetch', status: 'partial',
      result: { response_schemas: [
        { source_id: 'empty', capture_status: 'empty', upstream: { root_type: 'array', fields: [] }, normalized: null },
        { source_id: 'cached', capture_status: 'cached', upstream: null, normalized: null },
        { source_id: 'unavailable', capture_status: 'unavailable', upstream: null, normalized: null },
        { source_id: 'truncated', catalog_type: 'rss', capture_status: 'truncated', job_truncated: true, upstream: { root_type: 'object', truncated: true, fields: [{ path: 'items[].title', type: 'string', value: 'RAW_RESPONSE_SECRET' }] }, normalized: { root_type: 'array', fields: [{ path: '[].title', type: 'string', example: 'RAW_NORMALIZED_SECRET' }] } },
      ] },
    }
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><HeroResponseSchemaDetails job={job} sourceNames={new Map([['empty', 'Empty API'], ['cached', 'Cached API'], ['unavailable', 'Unavailable API'], ['truncated', 'Truncated API']])} /></QueryClientProvider>)

    const trigger = screen.getByRole('button', { name: '响应结构' })
    const disclosure = trigger.closest('[data-soft-disclosure="响应结构"]')
    const contentId = trigger.getAttribute('aria-controls')
    const content = contentId ? document.getElementById(contentId) : null
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(contentId).toBeTruthy()
    expect(content).toHaveAttribute('aria-hidden', 'true')
    expect(content).toHaveClass('duration-[var(--inteliscope-motion-disclosure)]', 'motion-reduce:transition-none')
    expect(disclosure).toHaveAttribute('data-disclosure-state', 'closed')
    await browser.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(content).toHaveAttribute('aria-hidden', 'false')
    expect(disclosure).toHaveAttribute('data-disclosure-state', 'open')
    expect(screen.getByText('上游成功返回空结果，本次没有可展示字段。')).toBeInTheDocument()
    expect(screen.getByText('本次使用共享缓存，未重新观察上游响应。')).toBeInTheDocument()
    expect(screen.getByText('本次运行未能记录上游响应结构。')).toBeInTheDocument()
    expect(screen.getAllByText('字段较多，已按安全上限截断。').length).toBeGreaterThan(0)
    expect(screen.getAllByText('字段路径').length).toBeGreaterThan(0)
    expect(screen.getAllByText('类型').length).toBeGreaterThan(0)
    expect(screen.getByText('items[].title')).toBeInTheDocument()
    expect(screen.getByText('[].title')).toBeInTheDocument()
    expect(screen.queryByText('RAW_RESPONSE_SECRET')).not.toBeInTheDocument()
    expect(screen.queryByText('RAW_NORMALIZED_SECRET')).not.toBeInTheDocument()
    await browser.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(content).toHaveAttribute('aria-hidden', 'true')
    expect(disclosure).toHaveAttribute('data-disclosure-state', 'closed')
  })

  it('loads the full job only after a compact summary disclosure opens', async () => {
    const browser = userEvent.setup()
    const summaryJob: Job = {
      id: 'summary-job',
      user_id: 'user-1',
      job_type: 'source_fetch',
      status: 'succeeded',
      result: { new_item_count: 1 },
    }
    const job = vi.fn().mockResolvedValue({
      ...summaryJob,
      result_json: {
        response_schemas: [{
          source_id: 'source-1',
          capture_status: 'captured',
          upstream: { root_type: 'object', fields: [{ path: 'title', type: 'string' }] },
          normalized: { root_type: 'array', fields: [] },
        }],
      },
    })
    const api = { job } as unknown as ServiceApi
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><HeroResponseSchemaDetails job={summaryJob} sourceNames={new Map([['source-1', 'Source One']])} api={api} userId="user-1" /></QueryClientProvider>)

    expect(job).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '响应结构' }))
    expect(await screen.findByText('Source One')).toBeInTheDocument()
    expect(job).toHaveBeenCalledWith('summary-job', expect.any(AbortSignal))
    expect(screen.getByText('title')).toBeInTheDocument()
  })
})
