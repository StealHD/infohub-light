import { useState } from 'react'

import { Chip, Popover } from '../../design-system'
import { actorOpsV2CandidateLabel, actorOpsV2PriceLabel, compactNumber, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export function ActorOpsV2ActorChip({ candidate, role }: { candidate: ActorOpsV2CandidateView | null; role: '主用' | '备用' }) {
  const [open, setOpen] = useState(false)
  if (!candidate) return <span className="type-meta text-muted">{role}未配置</span>
  const metadata = candidate.store_metadata
  const name = actorOpsV2CandidateLabel(candidate)
  return <Popover isOpen={open} onOpenChange={setOpen}>
    <Popover.Trigger<'button'>
      type="button"
      onMouseEnter={() => setOpen(true)}
      onFocus={() => setOpen(true)}
      className="min-w-0 rounded-lg outline-none focus-visible:outline-2 focus-visible:outline-focus"
      aria-label={`查看${name}商城信息`}
    >
      <Chip size="sm" variant="secondary" className="max-w-[min(220px,60vw)] cursor-pointer gap-1.5">
        <span className="text-muted">{role}</span><span className="truncate">{name}</span>
      </Chip>
    </Popover.Trigger>
    <Popover.Content placement="bottom start" offset={8} containerPadding={12} className="z-50 w-[min(340px,calc(100vw-24px))] p-0">
      <Popover.Dialog aria-label={`${name} 商城信息`} className="grid gap-3 p-4" onMouseLeave={() => setOpen(false)}>
        <div className="min-w-0"><Popover.Heading className="type-control truncate">{name}</Popover.Heading><p className="mt-1 break-all type-meta text-muted">{metadata?.actor_slug || '商城信息待更新'}</p></div>
        <p className="type-meta text-muted">{actorOpsV2PriceLabel(candidate)}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 type-meta">
          <Metric label="评分" value={metadata?.rating === null || metadata?.rating === undefined ? '—' : `${metadata.rating}（${compactNumber(metadata.review_count ?? null)}）`} />
          <Metric label="收藏" value={compactNumber(metadata?.bookmark_count ?? null)} />
          <Metric label="总用户" value={compactNumber(metadata?.total_users ?? null)} />
          <Metric label="月活" value={compactNumber(metadata?.monthly_active_users ?? null)} />
          <Metric label="Build" value={candidate.build_number || '已冻结'} />
          <Metric label="核验" value={`${candidate.evidence_progress.verified_bindings}/${candidate.evidence_progress.required_bindings}`} />
        </dl>
        {metadata?.developer_name && <p className="type-meta text-muted">开发者：{metadata.developer_name}{metadata.maintained_by_apify ? ' · Maintained by Apify' : ''}</p>}
        {metadata?.actor_slug && <a href={`https://apify.com/${encodeURIComponent(metadata.actor_slug).replace('%2F', '/')}`} target="_blank" rel="noopener noreferrer" className="type-control text-accent underline-offset-4 hover:underline">打开 Apify</a>}
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-muted">{label}</dt><dd className="mt-0.5 text-foreground">{value}</dd></div>
}
