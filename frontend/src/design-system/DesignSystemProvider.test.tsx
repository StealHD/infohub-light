import { render, screen } from '@testing-library/react'
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

describe('DesignSystemProvider', () => {
  it('marks the formal design-system root as the graphite-purple dark theme', () => {
    render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)

    const root = screen.getByTestId('content').parentElement
    expect(root).toHaveAttribute('data-theme', 'dark')
    expect(root).toHaveAttribute('data-inteliscope-theme', 'graphite-purple')
    expect(root).toHaveClass('inteliscope-design-system')
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
