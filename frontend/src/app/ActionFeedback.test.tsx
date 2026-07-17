import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ActionFeedbackProvider, useActionFeedback } from './ActionFeedback'

function Probe() {
  const feedback = useActionFeedback()
  return <>
    <button onClick={() => feedback.begin('fetch', 'source-a')}>start a</button>
    <button onClick={() => feedback.begin('fetch', 'source-b')}>start b</button>
    <button onClick={() => feedback.succeed('fetch', 'source-a', '来源 A 获取完成。')}>finish a</button>
    <button onClick={() => feedback.fail('fetch', 'source-b', '来源 B 获取失败。')}>fail b</button>
    <span data-testid="a">{feedback.phase('fetch', 'source-a') ?? 'idle'}</span>
    <span data-testid="b">{feedback.phase('fetch', 'source-b') ?? 'idle'}</span>
    <span data-testid="a-message">{feedback.message('fetch', 'source-a') ?? ''}</span>
    <span data-testid="b-message">{feedback.message('fetch', 'source-b') ?? ''}</span>
  </>
}

describe('ActionFeedbackProvider', () => {
  it('tracks independent entity actions and their terminal messages', async () => {
    const user = userEvent.setup()
    render(<ActionFeedbackProvider userId="user-1"><Probe /></ActionFeedbackProvider>)

    await user.click(screen.getByRole('button', { name: 'start a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('pending')
    expect(screen.getByTestId('b')).toHaveTextContent('idle')

    await user.click(screen.getByRole('button', { name: 'start b' }))
    await user.click(screen.getByRole('button', { name: 'finish a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('succeeded')
    expect(screen.getByTestId('b')).toHaveTextContent('pending')
    expect(screen.getByTestId('a-message')).toHaveTextContent('来源 A 获取完成。')

    await user.click(screen.getByRole('button', { name: 'fail b' }))
    expect(screen.getByTestId('b')).toHaveTextContent('failed')
    expect(screen.getByTestId('b-message')).toHaveTextContent('来源 B 获取失败。')
  })

  it('clears action state when the authenticated user changes', async () => {
    const user = userEvent.setup()
    const view = render(<ActionFeedbackProvider userId="user-1"><Probe /></ActionFeedbackProvider>)
    await user.click(screen.getByRole('button', { name: 'start a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('pending')

    view.rerender(<ActionFeedbackProvider userId="user-2"><Probe /></ActionFeedbackProvider>)
    expect(screen.getByTestId('a')).toHaveTextContent('idle')
  })
})
