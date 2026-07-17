import { expect, it } from 'vitest'
import * as DesignSystem from './index'

it('exposes workbench runtime components', () => {
  for (const name of ['AvatarRoot', 'AvatarImage', 'AvatarFallback', 'Button', 'Card', 'Chip', 'Icons']) {
    expect(DesignSystem[name as keyof typeof DesignSystem], name).toBeDefined()
  }
  expect(DesignSystem.Icons.Bookmark).toBeDefined()
})
