import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

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
    render(<HeroResponseSchemaDetails job={job} sourceNames={new Map([['empty', 'Empty API'], ['cached', 'Cached API'], ['unavailable', 'Unavailable API'], ['truncated', 'Truncated API']])} />)

    const trigger = screen.getByRole('button', { name: '响应结构' })
    const disclosure = trigger.closest('[data-soft-disclosure="响应结构"]')
    const contentId = trigger.getAttribute('aria-controls')
    const content = contentId ? document.getElementById(contentId) : null
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(contentId).toBeTruthy()
    expect(content).toHaveAttribute('aria-hidden', 'true')
    expect(content).toHaveClass('duration-200', 'motion-reduce:transition-none')
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
})
