import { expect, it } from 'vitest'
import * as DesignSystem from './index'

it('exposes workbench runtime components', () => {
  for (const name of ['anchoredTooltipProps', 'bottomAnchoredTooltipProps', 'topAnchoredTooltipProps', 'AvatarRoot', 'AvatarImage', 'AvatarFallback', 'Button', 'Card', 'Chip', 'InputGroup', 'Icons']) {
    expect(DesignSystem[name as keyof typeof DesignSystem], name).toBeDefined()
  }
  expect(DesignSystem.Icons.Bookmark).toBeDefined()
  expect(DesignSystem.anchoredTooltipProps).toEqual({
    placement: 'right',
    offset: 8,
    containerPadding: 8,
    shouldFlip: true,
  })
  expect(DesignSystem.topAnchoredTooltipProps).toEqual({
    placement: 'top',
    offset: 8,
    containerPadding: 8,
    shouldFlip: true,
  })
  expect(DesignSystem.bottomAnchoredTooltipProps).toEqual({
    placement: 'bottom',
    offset: 8,
    containerPadding: 8,
    shouldFlip: true,
  })
})
