import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ActionFeedbackProvider, useActionFeedback } from './ActionFeedback'

function useViewport(width: number) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn((query: string): MediaQueryList => {
      const max = query.match(/max-width:\s*(\d+(?:\.\d+)?)px/)
      return {
        matches: !max || width <= Number(max[1]),
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }
    }),
  })
}

function Probe() {
  const feedback = useActionFeedback()
  return <>
    <button onClick={() => feedback.begin('fetch', 'source-a')}>start a</button>
    <button onClick={() => feedback.begin('fetch', 'source-b')}>start b</button>
    <button onClick={() => feedback.succeed('fetch', 'source-a', '来源 A 获取完成。')}>finish a</button>
    <button onClick={() => feedback.fail('fetch', 'source-b', '来源 B 获取失败。')}>fail b</button>
    <span data-testid="a">{feedback.phase('fetch', 'source-a') ?? 'idle'}</span>
    <span data-testid="b">{feedback.phase('fetch', 'source-b') ?? 'idle'}</span>
  </>
}

describe('ActionFeedbackProvider', () => {
  it('tracks independent entity actions and announces terminal feedback', async () => {
    const user = userEvent.setup()
    render(<ActionFeedbackProvider userId="user-1"><Probe /></ActionFeedbackProvider>)

    await user.click(screen.getByRole('button', { name: 'start a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('pending')
    expect(screen.getByTestId('b')).toHaveTextContent('idle')

    await user.click(screen.getByRole('button', { name: 'start b' }))
    await user.click(screen.getByRole('button', { name: 'finish a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('succeeded')
    expect(screen.getByTestId('b')).toHaveTextContent('pending')
    expect(screen.getByRole('status')).toHaveTextContent('来源 A 获取完成。')

    await user.click(screen.getByRole('button', { name: 'fail b' }))
    expect(screen.getByTestId('b')).toHaveTextContent('failed')
    expect(screen.getByRole('alert')).toHaveTextContent('来源 B 获取失败。')
  })

  it('clears action state when the authenticated user changes', async () => {
    const user = userEvent.setup()
    const view = render(<ActionFeedbackProvider userId="user-1"><Probe /></ActionFeedbackProvider>)
    await user.click(screen.getByRole('button', { name: 'start a' }))
    expect(screen.getByTestId('a')).toHaveTextContent('pending')

    view.rerender(<ActionFeedbackProvider userId="user-2"><Probe /></ActionFeedbackProvider>)
    expect(screen.getByTestId('a')).toHaveTextContent('idle')
  })

  it('positions terminal feedback above the mobile bottom navigation', async () => {
    useViewport(390)
    const user = userEvent.setup()
    render(<ActionFeedbackProvider userId="user-1"><Probe /></ActionFeedbackProvider>)

    await user.click(screen.getByRole('button', { name: 'fail b' }))

    expect(screen.getByRole('alert').closest('.MuiSnackbar-root')).toHaveStyle({ bottom: '76px' })
  })
})
