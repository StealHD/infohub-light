export type SourceOverviewViewportAnchor = {
  kind: 'item' | 'source'
  id: string
  offset: number
  scrollTop?: number
}

export function readSourceOverviewViewportAnchor(
  scroll: HTMLDivElement,
  topInset: number,
): SourceOverviewViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const effectiveTop = bounds.top + topInset
  const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]'))
    .filter((candidate) => candidate.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
  if (row?.dataset.itemId && card) {
    return { kind: 'item', id: row.dataset.itemId, offset: card.getBoundingClientRect().top - effectiveTop, scrollTop: scroll.scrollTop }
  }
  const header = Array.from(scroll.querySelectorAll<HTMLElement>('[data-source-header]'))
    .filter((candidate) => candidate.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const section = header?.closest<HTMLElement>('[data-source-section]')
  if (!section?.dataset.sourceSectionId || !header) return null
  return { kind: 'source', id: section.dataset.sourceSectionId, offset: header.getBoundingClientRect().top - effectiveTop, scrollTop: scroll.scrollTop }
}
