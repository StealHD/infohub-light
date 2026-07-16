import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { FeedFilters } from './FeedFilters'

function renderFilters() {
  return render(
    <FeedFilters
      mode="all"
      onModeChange={vi.fn()}
      unreadFirst={false}
      onUnreadFirstChange={vi.fn()}
      sourceId=""
      onSourceChange={vi.fn()}
      channel=""
      onChannelChange={vi.fn()}
      topic=""
      onTopicChange={vi.fn()}
      minScore={undefined}
      onMinScoreChange={vi.fn()}
      sources={[["source-a", "OpenAI News"]]}
      channels={["AI"]}
      topics={["Codex"]}
      onClear={vi.fn()}
    />,
  )
}

describe('FeedFilters', () => {
  it('uses labelled Material UI comboboxes instead of overlapping native selects', async () => {
    const user = userEvent.setup()
    renderFilters()

    await user.click(screen.getByRole('button', { name: '更多筛选' }))
    const source = screen.getByRole('combobox', { name: '来源筛选' })
    const channel = screen.getByRole('combobox', { name: '频道筛选' })
    const topic = screen.getByRole('combobox', { name: '主题筛选' })
    const score = screen.getByRole('combobox', { name: '最低分筛选' })

    expect(source.tagName).not.toBe('SELECT')
    expect(channel.tagName).not.toBe('SELECT')
    expect(topic.tagName).not.toBe('SELECT')
    expect(score.tagName).not.toBe('SELECT')

    await user.click(source)
    expect(screen.getByRole('option', { name: '全部来源' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'OpenAI News' })).toBeInTheDocument()
  })
})
