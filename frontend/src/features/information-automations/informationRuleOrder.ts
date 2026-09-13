import type { InfiniteData } from '@tanstack/react-query'
import type { InformationPage, InformationRule } from '../../api/informationAutomationService'

type RulePages = InfiniteData<InformationPage<InformationRule>>

export function retainInformationRuleOrder(previous: unknown, next: unknown): RulePages {
  const incoming = next as RulePages
  const old = previous as RulePages | undefined
  if (!old?.pages?.length || !incoming?.pages?.length) return incoming
  const items = incoming.pages.flatMap((page) => page.items)
  const prior = old.pages.flatMap((page) => page.items.map((item) => item.id))
  const known = new Set(prior)
  const newcomers = items.filter((item) => !known.has(item.id)).map((item) => item.id)
  const rank = new Map([...newcomers, ...prior].map((id, index) => [id, index]))
  const ordered = [...items].sort((left, right) => (rank.get(left.id) ?? 0) - (rank.get(right.id) ?? 0))
  let offset = 0
  return { ...incoming, pages: incoming.pages.map((page) => {
    const arranged = ordered.slice(offset, offset + page.items.length)
    offset += page.items.length
    return { ...page, items: arranged }
  }) }
}
