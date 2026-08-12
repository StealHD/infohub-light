import { describe, expect, it, vi } from 'vitest'

import { readSourceOverviewViewportAnchor } from './sourceOverviewViewport'

function rect(top: number, bottom: number): DOMRect {
  return { top, bottom } as DOMRect
}

describe('source overview viewport model', () => {
  it('anchors the first visible item relative to the effective top inset', () => {
    const card = document.createElement('article')
    card.dataset.testid = 'workbench-card'
    card.getBoundingClientRect = vi.fn(() => rect(80, 120))
    const row = document.createElement('div')
    row.dataset.itemId = 'item-visible'
    row.getBoundingClientRect = vi.fn(() => rect(70, 130))
    row.append(card)
    const scroll = document.createElement('div')
    scroll.getBoundingClientRect = vi.fn(() => rect(20, 500))
    Object.defineProperty(scroll, 'scrollTop', { configurable: true, value: 44 })
    scroll.append(row)

    expect(readSourceOverviewViewportAnchor(scroll, 12)).toEqual({
      kind: 'item',
      id: 'item-visible',
      offset: 48,
      scrollTop: 44,
    })
  })

  it('falls back to a visible source header and returns null without candidates', () => {
    const header = document.createElement('header')
    header.dataset.sourceHeader = ''
    header.getBoundingClientRect = vi.fn(() => rect(90, 120))
    const section = document.createElement('section')
    section.dataset.sourceSection = ''
    section.dataset.sourceSectionId = 'source-1'
    section.append(header)
    const scroll = document.createElement('div')
    scroll.getBoundingClientRect = vi.fn(() => rect(25, 500))
    Object.defineProperty(scroll, 'scrollTop', { configurable: true, value: 16 })
    scroll.append(section)

    expect(readSourceOverviewViewportAnchor(scroll, 15)).toEqual({
      kind: 'source',
      id: 'source-1',
      offset: 50,
      scrollTop: 16,
    })
    scroll.replaceChildren()
    expect(readSourceOverviewViewportAnchor(scroll, 15)).toBeNull()
  })
})
