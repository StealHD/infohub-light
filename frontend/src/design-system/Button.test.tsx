import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Button } from './Button'
import { DesignSystemProvider } from './DesignSystemProvider'

describe('Button', () => {
  it('adds a 44px coarse-pointer target only for icon-only actions', () => {
    render(<MemoryRouter><DesignSystemProvider>
      <Button isIconOnly aria-label="关闭">×</Button>
      <Button>保存</Button>
    </DesignSystemProvider></MemoryRouter>)

    expect(screen.getByRole('button', { name: '关闭' })).toHaveClass('pointer-coarse:min-h-11', 'pointer-coarse:min-w-11')
    expect(screen.getByRole('button', { name: '保存' })).not.toHaveClass('pointer-coarse:min-h-11')
  })
})
