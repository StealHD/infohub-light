import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Job } from '../../api/types'
import { HeroResponseSchemaDetails } from './HeroResponseSchemaDetails'

describe('HeroResponseSchemaDetails', () => {
  it('presents safe empty, cached, unavailable and truncated schema states without raw values', () => {
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
  })
})
