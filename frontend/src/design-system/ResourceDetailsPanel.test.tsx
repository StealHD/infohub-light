import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from './DesignSystemProvider'
import { ResourceDetailsPanel } from './ResourceDetailsPanel'
import { resourceDetailsWidthKey } from './resourceDetailsPreference'

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  window.dispatchEvent(new Event('resize'))
}

beforeEach(() => {
  window.localStorage.clear()
  setViewport(1440)
})

it('supports bounded keyboard resizing, reset and account-isolated persistence', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<MemoryRouter><DesignSystemProvider><ResourceDetailsPanel open onClose={vi.fn()} userId="alice" title="任务详情"><p>内容</p></ResourceDetailsPanel></DesignSystemProvider></MemoryRouter>)
  const panel = screen.getByRole('complementary', { name: '自动化任务详情' })
  const separator = screen.getByRole('separator', { name: '调整任务列表和详情宽度' })
  expect(panel).toHaveStyle({ '--inteliscope-disclosure-width': '400px' })
  separator.focus(); await user.keyboard('{Shift>}{ArrowLeft}{/Shift}')
  expect(panel).toHaveStyle({ '--inteliscope-disclosure-width': '464px' })
  await user.keyboard('{End}')
  expect(panel).toHaveStyle({ '--inteliscope-disclosure-width': '558px' })
  await user.keyboard('{Home}')
  expect(panel).toHaveStyle({ '--inteliscope-disclosure-width': '320px' })
  await user.dblClick(separator)
  expect(panel).toHaveStyle({ '--inteliscope-disclosure-width': '400px' })
  expect(JSON.parse(localStorage.getItem(resourceDetailsWidthKey('alice')) || '{}')).toEqual({ width: 400 })
  rerender(<MemoryRouter><DesignSystemProvider><ResourceDetailsPanel open onClose={vi.fn()} userId="bob" title="任务详情"><p>内容</p></ResourceDetailsPanel></DesignSystemProvider></MemoryRouter>)
  expect(screen.getByRole('complementary', { name: '自动化任务详情' })).toHaveStyle({ '--inteliscope-disclosure-width': '400px' })
  expect(localStorage.getItem(resourceDetailsWidthKey('bob'))).toBeNull()
})

it('switches to a drawer when the list cannot retain 640px', () => {
  setViewport(1024)
  render(<MemoryRouter><DesignSystemProvider><ResourceDetailsPanel open onClose={vi.fn()} userId="alice" title="任务详情"><p>抽屉内容</p></ResourceDetailsPanel></DesignSystemProvider></MemoryRouter>)
  expect(screen.queryByRole('separator', { name: '调整任务列表和详情宽度' })).not.toBeInTheDocument()
  expect(screen.getByText('抽屉内容')).toBeVisible()
})
