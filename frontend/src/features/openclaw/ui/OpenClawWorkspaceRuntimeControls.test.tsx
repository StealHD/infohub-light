import { describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent, waitFor, chatController } from '../OpenClawConversation.test.support'
import OpenClawWorkspaceRuntimeControls from './OpenClawWorkspaceRuntimeControls'

function controller(overrides = {}) {
  return chatController({ models: [{ id: 'openai/gpt', name: 'GPT', provider: 'openai', reasoning: true }], thinkingOptions: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }], runtimeSelection: { modelId: 'openai/gpt', thinkingLevel: 'high', defaultThinkingLevel: 'low' }, ...overrides })
}

describe('workspace effort picker', () => {
  it.each([
    ['high', false, 'none'], ['ultra', false, 'ultra'], ['high', true, 'fast'], ['ultra', true, 'fast'],
  ])('uses %s / Fast %s to select the %s decoration without writing settings', async (thinkingLevel, fastMode, effect) => {
    const user = userEvent.setup()
    const chat = controller({ thinkingOptions: [{ id: 'high', label: '高' }, { id: 'ultra', label: 'Ultra' }], runtimeSelection: { modelId: 'openai/gpt', thinkingLevel, fastMode } })
    render(<OpenClawWorkspaceRuntimeControls chat={chat as never} />)
    await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
    const slider = screen.getByRole('slider').closest('.effort-slider')!
    expect(slider).toHaveAttribute('data-effect', effect)
    expect(slider.querySelectorAll('.effort-slider-sparks i')).toHaveLength(12)
    expect(slider.querySelector('.effort-slider-sparks')).toHaveAttribute('aria-hidden', 'true')
    expect(chat.setThinking).not.toHaveBeenCalled()
    expect(chat.setFastMode).not.toHaveBeenCalled()
  })
  it('resets through one pending operation and preserves the confirmed level on failure', async () => {
    const user = userEvent.setup()
    let finish!: (success: boolean) => void
    const setThinking = vi.fn(() => new Promise<boolean>((resolve) => { finish = resolve }))
    render(<OpenClawWorkspaceRuntimeControls chat={controller({ setThinking }) as never} />)
    await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
    const reset = screen.getByRole('button', { name: '恢复默认思考' })
    await user.dblClick(reset)
    expect(setThinking).toHaveBeenCalledTimes(1)
    expect(setThinking).toHaveBeenCalledWith('low')
    expect(reset).toBeDisabled()
    finish(false)
    await screen.findByText('设置未能更新，请重试。')
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '高')
    expect(screen.getByRole('button', { name: 'Fast 快速模式' })).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(reset).toBeEnabled())
  })

  it('commits a Gateway-provided level with the keyboard and restores trigger focus', async () => {
    const user = userEvent.setup()
    const chat = controller()
    render(<OpenClawWorkspaceRuntimeControls chat={chat as never} />)
    const trigger = screen.getByRole('button', { name: /OpenClaw 模型/u })
    await user.click(trigger)
    screen.getByRole('slider').focus()
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => expect(chat.setThinking).toHaveBeenCalledWith('low'))
    await user.keyboard('{Escape}')
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('uses a compact model back action and keeps the scrollable list scrollbar hidden', async () => {
    const user = userEvent.setup()
    render(<OpenClawWorkspaceRuntimeControls chat={controller() as never} />)
    await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
    await user.click(screen.getByRole('button', { name: /选择模型：/u }))
    expect(screen.getByRole('button', { name: '返回思考程度' })).toBeVisible()
    expect(screen.queryByText('思考程度', { selector: 'button' })).not.toBeInTheDocument()
    const list = screen.getByRole('listbox', { name: 'OpenClaw 模型' })
    expect(list).toHaveClass('effort-model-list')
    await user.click(screen.getByRole('button', { name: '返回思考程度' }))
    expect(screen.getByRole('slider', { name: '思考程度' })).toBeVisible()
  })

  it('explains unsupported reasoning without inventing available levels', async () => {
    const user = userEvent.setup()
    render(<OpenClawWorkspaceRuntimeControls chat={controller({ models: [{ id: 'openai/gpt', name: 'GPT', provider: 'openai', reasoning: false }] }) as never} />)
    await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
    expect(screen.getByRole('slider')).toBeDisabled()
    expect(screen.getByText('此模型未提供推理档位。')).toBeVisible()
    expect(screen.getByRole('button', { name: '选择模型：GPT' })).toBeEnabled()
  })
})


it('does not show a token usage reminder when switching to Ultra fails', async () => {
  const user = userEvent.setup()
  render(<OpenClawWorkspaceRuntimeControls chat={controller({ thinkingOptions: [{ id: 'high', label: '高' }, { id: 'ultra', label: 'Ultra' }], setThinking: vi.fn().mockResolvedValue(false) }) as never} />)
  await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
  screen.getByRole('slider').focus()
  await user.keyboard('{End}')
  await screen.findByText('设置未能更新，请重试。')
  expect(screen.queryByText('Ultra 会消耗更多 Token')).not.toBeInTheDocument()
  expect(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '高')
})


it('excludes off and auto without writing defaults during rendering', async () => {
  const user = userEvent.setup()
  const chat = controller({ thinkingOptions: [{ id: 'off', label: '关' }, { id: 'auto', label: '自动' }, { id: 'low', label: '低' }, { id: 'high', label: '高' }], runtimeSelection: { modelId: 'openai/gpt', thinkingLevel: null, defaultThinkingLevel: 'low' } })
  render(<OpenClawWorkspaceRuntimeControls chat={chat as never} />)
  await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
  expect(screen.getByRole('slider')).toHaveAttribute('max', '1')
  expect(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '低')
  expect(screen.queryByText('自动')).not.toBeInTheDocument()
  expect(screen.queryByText('关')).not.toBeInTheDocument()
  expect(chat.setThinking).not.toHaveBeenCalled()
})

it('does not claim an unknown or hidden current level is the lowest level', async () => {
  const user = userEvent.setup()
  const chat = controller({ runtimeSelection: { modelId: 'openai/gpt', thinkingLevel: 'off' } })
  render(<OpenClawWorkspaceRuntimeControls chat={chat as never} />)
  await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
  expect(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '未选择思考档位')
  expect(screen.getByRole('button', { name: '恢复默认思考' })).toBeDisabled()
  screen.getByRole('slider').focus()
  await user.keyboard('{Home}')
  await waitFor(() => expect(chat.setThinking).toHaveBeenCalledWith('low'))
})

it('rechecks an explicitly reselected model without a success notice', async () => {
  const user = userEvent.setup()
  const chat = controller({ setModel: vi.fn().mockResolvedValue(true) })
  render(<OpenClawWorkspaceRuntimeControls chat={chat as never} />)
  await user.click(screen.getByRole('button', { name: /OpenClaw 模型/u }))
  await user.click(screen.getByRole('button', { name: /选择模型：/u }))
  await user.click(screen.getByRole('option', { name: /GPT/ }))
  expect(chat.setModel).toHaveBeenCalledWith('openai/gpt')
  expect(chat.setModel).toHaveBeenCalledTimes(1)
  expect(screen.queryByText(/模型已切换/)).not.toBeInTheDocument()
})
