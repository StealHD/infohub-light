import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { anchoredTooltipProps } from './tooltip'
import { TooltipTriggerButton } from './TooltipTriggerButton'
import { Tooltip } from './index'

describe('TooltipTriggerButton', () => {
  it('lets an explicit semantic background replace the transparent default', () => {
    render(<TooltipTriggerButton aria-label="强调动作" className="bg-accent">发送</TooltipTriggerButton>)

    const trigger = screen.getByRole('button', { name: '强调动作' })
    expect(trigger).toHaveClass('bg-accent')
    expect(trigger).not.toHaveClass('bg-transparent')
  })

  it('opens its nearby tooltip from the actual hovered button', async () => {
    const user = userEvent.setup()
    render(<Tooltip delay={0}>
      <TooltipTriggerButton aria-label="说明">i</TooltipTriggerButton>
      <Tooltip.Content {...anchoredTooltipProps}>附近说明</Tooltip.Content>
    </Tooltip>)

    const trigger = screen.getByRole('button', { name: '说明' })
    await user.hover(trigger)

    expect(trigger).toHaveClass('bg-transparent')
    expect(await screen.findByRole('tooltip')).toHaveTextContent('附近说明')
    expect(trigger).toHaveAttribute('aria-describedby')
  })

  it('opens its nearby tooltip from keyboard focus', async () => {
    const user = userEvent.setup()
    render(<Tooltip delay={0}>
      <TooltipTriggerButton aria-label="键盘说明">i</TooltipTriggerButton>
      <Tooltip.Content {...anchoredTooltipProps}>键盘附近说明</Tooltip.Content>
    </Tooltip>)

    await user.tab()

    expect(screen.getByRole('button', { name: '键盘说明' })).toHaveFocus()
    expect(await screen.findByRole('tooltip')).toHaveTextContent('键盘附近说明')
  })
})
