import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ChatMarkdown } from './ChatMarkdown'

describe('ChatMarkdown', () => {
  it('formats assistant analysis while keeping links and media safe', () => {
    const { container } = render(<ChatMarkdown text={'## 诊断结果\n\n---\n\n### 来源\n- **状态**：`failing`\n- 下一步：检查 DNS\n\n| 来源 | 结果 |\n| --- | --- |\n| Apple | 失败 |\n\n[证据](https://example.com/log) https://example.com/help [执行](javascript:alert(1)) <b>原文</b> ![远程图](https://example.com/image.png)'} />)

    expect(screen.getByRole('heading', { name: '诊断结果' })).toHaveClass('type-page-title')
    expect(screen.getByRole('heading', { name: '来源' })).toHaveClass('type-card-title')
    expect(container.querySelector('hr')).not.toBeNull()
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('strong')).toHaveTextContent('状态')
    expect(container.querySelector('code')).toHaveTextContent('failing')
    expect(container.querySelector('table')).toHaveTextContent('Apple')
    for (const link of screen.getAllByRole('link')) {
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
      expect(link.getAttribute('href')).toMatch(/^https:\/\//u)
    }
    expect(screen.getAllByRole('link')).toHaveLength(2)
    expect(container).toHaveTextContent('执行')
    expect(container).toHaveTextContent('<b>原文</b>')
    expect(container.querySelector('b')).toBeNull()
    expect(container).toHaveTextContent('远程图')
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders an incomplete stream and updates it when the answer finishes', () => {
    const { rerender } = render(<ChatMarkdown text={'## 诊断\n- **进行'} />)
    expect(screen.getByRole('heading', { name: '诊断' })).toBeInTheDocument()
    rerender(<ChatMarkdown text={'## 诊断\n- **进行中**'} />)
    expect(screen.getByText('进行中')).toHaveProperty('tagName', 'STRONG')
  })
})
