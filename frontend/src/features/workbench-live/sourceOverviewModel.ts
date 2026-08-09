import type { WorkbenchCardModel } from './workbenchModel'

export type SourceOverviewSectionModel = {
  id: string
  sourceId?: string
  sourceName: string
  sourceAvatar?: string
  platformLabel: string
  cards: WorkbenchCardModel[]
  itemCount: number
  topicCount: number
  topics: string[]
  latestPublishedAt?: string
  contentFingerprint: string
}

type MutableSection = SourceOverviewSectionModel & {
  order: number
  latestPublishedTimestamp: number | null
  topicStats: Map<string, { count: number; order: number }>
}

export function buildSourceOverviewSections(cards: WorkbenchCardModel[]): SourceOverviewSectionModel[] {
  const sections = new Map<string, MutableSection>()

  cards.forEach((card, cardOrder) => {
    const identity = sourceIdentity(card)
    let section = sections.get(identity.key)
    if (!section) {
      section = {
        id: identity.key,
        sourceId: identity.sourceId,
        sourceName: card.source,
        sourceAvatar: card.sourceAvatar,
        platformLabel: card.platformLabel,
        cards: [],
        itemCount: 0,
        topicCount: 0,
        topics: [],
        latestPublishedAt: undefined,
        contentFingerprint: '',
        order: sections.size,
        latestPublishedTimestamp: null,
        topicStats: new Map(),
      }
      sections.set(identity.key, section)
    }

    section.cards.push(card)
    section.itemCount += 1
    const published = publishedTimestamp(card)
    if (published !== null && (section.latestPublishedTimestamp === null || published > section.latestPublishedTimestamp)) {
      section.latestPublishedTimestamp = published
      section.latestPublishedAt = card.item.presentation?.timing?.published_at || card.item.published_at
    }

    const seenTopics = new Set<string>()
    card.topics.forEach((topic) => {
      const label = normalizeTopic(topic)
      if (!label || seenTopics.has(label)) return
      seenTopics.add(label)
      const existing = section!.topicStats.get(label)
      if (existing) existing.count += 1
      else section!.topicStats.set(label, { count: 1, order: cardOrder })
    })
  })

  return Array.from(sections.values())
    .map((section) => ({
      ...section,
      topicCount: section.topicStats.size,
      topics: Array.from(section.topicStats.entries())
        .sort((left, right) => right[1].count - left[1].count || left[1].order - right[1].order)
        .slice(0, 3)
        .map(([topic]) => topic),
    }))
    .sort((left, right) => {
      const leftTimestamp = left.latestPublishedTimestamp
      const rightTimestamp = right.latestPublishedTimestamp
      if (leftTimestamp !== null && rightTimestamp !== null) return rightTimestamp - leftTimestamp || left.order - right.order
      if (leftTimestamp !== null) return -1
      if (rightTimestamp !== null) return 1
      return left.order - right.order
    })
    .map((section) => ({
      id: section.id,
      sourceId: section.sourceId,
      sourceName: section.sourceName,
      sourceAvatar: section.sourceAvatar,
      platformLabel: section.platformLabel,
      cards: section.cards,
      itemCount: section.itemCount,
      topicCount: section.topicCount,
      topics: section.topics,
      latestPublishedAt: section.latestPublishedAt,
      contentFingerprint: section.cards.map((card) => [
        card.id,
        card.displayKind === 'social' ? card.primaryText : card.title,
        card.summary ?? '',
        card.publishedAt ?? '',
      ].join('\u0001')).join('\u0002'),
    }))
}

function sourceIdentity(card: WorkbenchCardModel): { key: string; sourceId?: string } {
  const item = card.item
  const sourceId = item.presentation?.source?.id
    || item.source_id
    || item.source_ids?.[0]
    || item.subscription_id
    || item.subscription_ids?.[0]
  if (sourceId) return { key: `source:${sourceId}`, sourceId }

  const sourceType = item.presentation?.source?.catalog_type || item.source_type || card.platformLabel
  return { key: `fallback:${normalizeIdentity(sourceType)}:${normalizeIdentity(card.source)}` }
}

function publishedTimestamp(card: WorkbenchCardModel): number | null {
  const value = card.item.presentation?.timing?.published_at || card.item.published_at
  if (!value) return null
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : null
}

function normalizeTopic(value: string): string {
  return value.trim().replace(/^#+\s*/u, '').trim()
}

function normalizeIdentity(value: string): string {
  return value.trim().normalize('NFKC').toLocaleLowerCase() || 'unknown'
}
