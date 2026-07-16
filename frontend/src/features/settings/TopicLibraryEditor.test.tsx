import type { ComponentType } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { UiProvider } from '../../ui'
import * as settingsPageModule from './SettingsPage'

describe('TopicLibraryEditor', () => {
  it('adds, searches, removes, restores and saves topic chips', async () => {
    const user = userEvent.setup()
    const candidate = (settingsPageModule as unknown as { TopicLibraryEditor?: ComponentType<{ topics: string[]; pending?: boolean; onSave: (topics: string[]) => void }> }).TopicLibraryEditor
    expect(candidate).toBeTypeOf('function')
    const TopicLibraryEditor = candidate!
    const onSave = vi.fn()
    render(<UiProvider><TopicLibraryEditor topics={['AI Agent', 'RAG/MCP']} onSave={onSave} /></UiProvider>)

    await user.type(screen.getByRole('textbox', { name: '新增主题' }), '模型发布')
    await user.click(screen.getByRole('button', { name: '添加主题' }))
    expect(screen.getByText('模型发布')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '删除 RAG/MCP' }))
    expect(screen.queryByText('RAG/MCP')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '撤销更改' }))
    expect(screen.getByText('RAG/MCP')).toBeInTheDocument()
    expect(screen.queryByText('模型发布')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '删除 RAG/MCP' }))
    await user.click(screen.getByRole('button', { name: '保存更改' }))
    expect(onSave).toHaveBeenCalledWith(['AI Agent'])
  })
})
