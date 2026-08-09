import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

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
import {
  DEFAULT_THEME_PREFERENCE,
  readThemePreference,
  THEME_PREFERENCE_STORAGE_KEY,
} from './themePreference'

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
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('defaults to the existing dark graphite theme and ignores system changes', () => {
    const theme = installSystemTheme(false)
    render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)

    const root = screen.getByTestId('content').parentElement
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(root).toHaveAttribute('data-inteliscope-theme', 'graphite-purple')
    expect(root).toHaveClass('inteliscope-design-system')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')

    act(() => theme.setDark(true))
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('restores a valid persisted light preference on both theme roots', () => {
    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify({
      themeName: 'graphite-purple',
      colorMode: 'light',
    }))
    render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)

    const root = screen.getByTestId('content').parentElement
    expect(root).toHaveAttribute('data-theme', 'light')
    expect(root).toHaveAttribute('data-inteliscope-theme', 'graphite-purple')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('sanitizes malformed or unsupported preferences back to dark graphite', () => {
    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify({
      themeName: 'unsupported',
      colorMode: 'system',
    }))
    expect(readThemePreference()).toEqual(DEFAULT_THEME_PREFERENCE)

    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, '{broken')
    expect(readThemePreference()).toEqual(DEFAULT_THEME_PREFERENCE)
  })

  it('renders the Inteliscope brand mark as a two-part current-color glyph', () => {
    const { container } = render(<MemoryRouter><DesignSystemProvider><Icons.InteliscopeMark aria-hidden="true" /></DesignSystemProvider></MemoryRouter>)

    const mark = container.querySelector('[data-inteliscope-mark]')
    expect(mark).not.toBeNull()
    if (!mark) throw new Error('Inteliscope mark was not rendered')
    expect(mark).toHaveAttribute('fill', 'currentColor')
    expect(mark.querySelectorAll('path')).toHaveLength(2)
    expect(mark.querySelector('circle')).toBeNull()
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
