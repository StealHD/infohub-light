import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import {
  Button,
  Card,
  Chip,
  ComboBox,
  Description,
  DesignSystemProvider,
  Drawer,
  FieldError,
  Form,
  Icons,
  Input,
  Label,
  Link,
  Modal,
  ScrollShadow,
  SearchField,
  Select,
  Skeleton,
  Table,
  Tabs,
  TextArea,
  TextField,
  Toast,
  Tooltip,
} from '.'
import { readSystemTheme } from './systemTheme'

function installSystemTheme(initialDark: boolean) {
  let dark = initialDark
  const listeners = new Set<(event: MediaQueryListEvent) => void>()
  const media = {
    get matches() { return dark },
    media: '(prefers-color-scheme: dark)',
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    dispatchEvent: () => false,
  } as MediaQueryList
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => media })
  return {
    setDark(value: boolean) {
      dark = value
      listeners.forEach((listener) => listener({ matches: value, media: media.media } as MediaQueryListEvent))
    },
  }
}

describe('DesignSystemProvider', () => {
  it('marks the formal design-system root with the system dark theme', () => {
    installSystemTheme(true)
    render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)

    const root = screen.getByTestId('content').parentElement
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(root).toHaveAttribute('data-inteliscope-theme', 'graphite-purple')
    expect(root).toHaveClass('inteliscope-design-system')
  })

  it('starts in system light mode and updates the app and document when the system changes', () => {
    const theme = installSystemTheme(false)
    render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)

    const root = screen.getByTestId('content').parentElement
    expect(root).toHaveAttribute('data-theme', 'light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')

    act(() => theme.setDark(true))
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('uses the light fallback when system color-scheme detection is unavailable', () => {
    const matchMedia = window.matchMedia
    try {
      Object.defineProperty(window, 'matchMedia', { configurable: true, value: undefined })
      expect(readSystemTheme()).toBe('light')
    } finally {
      Object.defineProperty(window, 'matchMedia', { configurable: true, value: matchMedia })
    }
  })

  it('routes HeroUI links through React Router without a document navigation', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/']}>
        <DesignSystemProvider>
          <Routes>
            <Route path="/" element={<Link href="/settings">打开设置</Link>} />
            <Route path="/settings" element={<h1>设置</h1>} />
          </Routes>
        </DesignSystemProvider>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('link', { name: '打开设置' }))
    expect(screen.getByRole('heading', { name: '设置' })).toBeInTheDocument()
  })

  it('centralizes the approved HeroUI primitives, form controls and Lucide icons', () => {
    expect([
      Card, Button, SearchField, Chip, Tabs, Modal, Drawer, Select, ComboBox,
      Table, Skeleton, Toast, Tooltip, ScrollShadow, TextArea,
      Form, TextField, Input, Label, Description, FieldError, Icons.Search,
    ]).not.toContain(undefined)
  })
})
