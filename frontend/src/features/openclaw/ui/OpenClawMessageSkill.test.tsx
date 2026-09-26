import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ConversationTurn } from './OpenClawMessageViews'

describe('selected Skill message label', () => {
  it.each(['compact', 'workspace'] as const)('appears inside the user bubble in %s conversations', (variant) => {
    render(<ConversationTurn role="user" text="小王子" skillName="book-skill" hasNext={false} variant={variant} />)
    const message = screen.getByRole('article', { name: '你的消息' })
    const bubble = message.querySelector('[data-chat-message-bubble]')!
    expect(bubble).toContainElement(screen.getByText('Skill：book-skill'))
    expect(bubble).toContainElement(screen.getByText('小王子'))
    expect(message).not.toHaveTextContent(/已执行|已调用/u)
  })
  it('keeps ordinary messages free of Skill metadata', () => {
    render(<ConversationTurn role="user" text="介绍 book-skill" hasNext={false} />)
    expect(screen.queryByText(/Skill：/u)).not.toBeInTheDocument()
  })
})
