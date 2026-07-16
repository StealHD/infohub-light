import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Job } from '../../api/types'
import { ResponseSchemaDetails } from './ResponseSchemaDetails'

const job: Job = {
  id: 'job-schema',
  user_id: 'user-1',
  job_type: 'source_fetch',
  source_id: 'source-x',
  status: 'succeeded',
  result: {
    response_schemas: [{
      source_id: 'source-x',
      catalog_type: 'apify_social',
      capture_status: 'captured',
      upstream: {
        root_type: 'array',
        fields: [
          { path: '[].author.profilePicture', type: 'string' },
          { path: '[].likeCount', type: 'integer' },
        ],
      },
      normalized: {
        root_type: 'array',
        fields: [
          { path: '[].author_avatar', type: 'string' },
          { path: '[].metadata.like_count', type: 'integer' },
        ],
      },
    }],
  },
}

describe('ResponseSchemaDetails', () => {
  it('shows upstream and normalized field paths and types without response values', async () => {
    const user = userEvent.setup()
    render(<ResponseSchemaDetails job={job} sourceNames={new Map([['source-x', 'X · @example']])} />)

    expect(screen.getByText('[].author.profilePicture')).not.toBeVisible()
    await user.click(screen.getByText('响应结构'))

    expect(screen.getByText('X · @example')).toBeInTheDocument()
    expect(screen.getByText('上游原始结构')).toBeInTheDocument()
    expect(screen.getByText('系统标准化结构')).toBeInTheDocument()
    expect(screen.getByText('[].author.profilePicture')).toBeInTheDocument()
    expect(screen.getByText('[].author_avatar')).toBeInTheDocument()
    expect(screen.getAllByText('integer')).toHaveLength(2)
    expect(screen.queryByText(/profile_images\/secret-value/)).not.toBeInTheDocument()
  })

  it('explains legacy jobs that do not contain response schema data', async () => {
    const user = userEvent.setup()
    const legacy = { ...job, result: { item_count: 1 } }
    render(<ResponseSchemaDetails job={legacy} sourceNames={new Map()} />)
    await user.click(screen.getByText('响应结构'))
    expect(screen.getByText('本次运行未记录响应结构。')).toBeInTheDocument()
  })
})
