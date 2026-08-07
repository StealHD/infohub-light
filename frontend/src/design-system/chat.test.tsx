import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PromptSuggestion } from './chat'

describe('PromptSuggestion', () => {
  it('provides accessible, composable prompt starter slots', async () => {
    const onPress = vi.fn()
    const user = userEvent.setup()
    render(<PromptSuggestion>
      <PromptSuggestion.Header>
        <PromptSuggestion.Title>从哪里开始？</PromptSuggestion.Title>
        <PromptSuggestion.Description>选择一个建议后继续编辑。</PromptSuggestion.Description>
      </PromptSuggestion.Header>
      <PromptSuggestion.Items aria-label="问题建议">
        <PromptSuggestion.Item aria-label="诊断任务" onPress={onPress}>
          <span>
            <PromptSuggestion.ItemTitle>诊断任务</PromptSuggestion.ItemTitle>
            <PromptSuggestion.ItemDescription>检查失败原因。</PromptSuggestion.ItemDescription>
          </span>
        </PromptSuggestion.Item>
      </PromptSuggestion.Items>
    </PromptSuggestion>)

    expect(screen.getByRole('heading', { name: '从哪里开始？' })).toHaveClass('prompt-suggestion__title', 'type-page-title')
    expect(screen.getByLabelText('问题建议')).toHaveClass('prompt-suggestion__items')
    const item = screen.getByRole('button', { name: '诊断任务' })
    expect(item).toHaveClass('prompt-suggestion__item', 'min-h-14', 'border', 'border-separator')
    expect(screen.getByText('检查失败原因。')).toHaveClass('prompt-suggestion__item-description', 'type-meta')

    await user.click(item)
    expect(onPress).toHaveBeenCalledTimes(1)
  })
})
