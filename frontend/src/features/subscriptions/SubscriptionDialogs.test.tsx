import type { ComponentType } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { UiProvider } from '../../ui'
import { ActionFeedbackProvider } from '../../app/ActionFeedback'
import { SourceForm } from './SubscriptionDialogs'

describe('SourceForm taxonomy controls', () => {
  it('uses channel options and a free-solo topic picker instead of comma-separated inputs', async () => {
    const user = userEvent.setup()
    const Form = SourceForm as ComponentType<Record<string, unknown>>
    const onSubmit = vi.fn()
    render(<UiProvider><ActionFeedbackProvider userId="user-1"><Form
      definition={{ type: 'rss', fields: [{ name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' }] }}
      source={{
        id: 'source-1', type: 'rss', display_name: 'Feed', scope: 'workspace', enabled: true,
        default_channel: 'AI', default_topics: ['旧主题'], config: { url: 'https://example.com/feed.xml' },
      }}
      secrets={[]}
      allowSecret={false}
      scopes={['workspace']}
      taxonomy={{ channels: ['AI', '工作/项目', '其他'], topics: ['AI Agent', '模型发布'] }}
      onSubmit={onSubmit}
      submitLabel="保存来源"
    /></ActionFeedbackProvider></UiProvider>)

    const channel = screen.getByRole('combobox', { name: '默认频道' })
    await user.click(channel)
    await user.click(screen.getByRole('option', { name: '工作/项目' }))

    const topics = screen.getByRole('combobox', { name: '默认主题' })
    expect(screen.getByText('旧主题')).toBeInTheDocument()
    expect(screen.getByText('已停用')).toBeInTheDocument()
    await user.type(topics, '自定义主题{enter}')
    expect(screen.getByText('自定义主题')).toBeInTheDocument()
    expect(screen.queryByText('多个主题使用逗号分隔')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '保存来源' }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      default_channel: '工作/项目',
      default_topics: ['旧主题', '自定义主题'],
    }))
  }, 10_000)
})
