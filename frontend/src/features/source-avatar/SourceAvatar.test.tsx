import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SourceAvatar } from './SourceAvatar'

function renderAvatar(props: Parameters<typeof SourceAvatar>[0]) {
  return render(<SourceAvatar {...props} />)
}

class LoadedImage extends EventTarget {
  complete = true
  naturalWidth = 32
  private value = ''

  get src() {
    return this.value
  }

  set src(value: string) {
    this.value = value
  }
}

describe('SourceAvatar', () => {
  it('renders only the authenticated local media URL as the source image', async () => {
    vi.stubGlobal('Image', LoadedImage)
    try {
      renderAvatar({
        name: '食贫道',
        avatarUrl: '/api/media/med_bilibili',
        platform: 'bilibili',
      })

      expect(await screen.findByRole('img', { name: '食贫道' })).toHaveAttribute(
        'src',
        '/api/media/med_bilibili',
      )
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('keeps a platform or source-name fallback available without an image', () => {
    const view = renderAvatar({
      name: 'OpenAI Releases',
      platform: 'github_release',
    })

    expect(screen.getByLabelText('OpenAI Releases 来源标识')).toHaveTextContent('GH')

    view.rerender(
      <SourceAvatar name="食贫道" platform="bilibili" />,
    )
    expect(screen.getByLabelText('食贫道 来源标识')).toHaveTextContent('食贫')
  })

  it('rejects an upstream avatar URL at the rendering boundary', () => {
    const view = renderAvatar({
      name: 'Remote source',
      avatarUrl: 'https://example.com/avatar.png',
      platform: 'rss',
    })

    expect(view.container.querySelector('img')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Remote source 来源标识')).toBeInTheDocument()
  })
})
