import type { MouseEvent, ReactNode } from 'react'
import { useState } from 'react'

import type { FeedItem, SourceHealthItem, UserItemState } from '../../api/types'
import {
  Alert,
  Avatar,
  Badge,
  Box,
  Button,
  Divider,
  EmptyState,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  Menu,
  MenuItem,
  Skeleton,
  Stack,
  Status,
  Surface,
  Tooltip,
  Typography,
  uiLayout,
  uiRadii,
} from '../../ui'
import {
  ArrowBackRounded,
  BookmarkBorderRounded,
  BookmarkRounded,
  CheckRounded,
  CloseRounded,
  ContentCopyRounded,
  MoreHorizRounded,
  OpenInNewRounded,
  RadioRounded,
  StarBorderRounded,
  StarRounded,
} from '../../ui/icons'
import { relativeTime, resolveItemHealth, safeExternalUrl, signalText } from './feedModel'

type ItemStateAction = keyof Pick<UserItemState, 'is_read' | 'is_saved' | 'is_later' | 'dismissed'>

type FeedWorkspaceProps = {
  title: string
  description: string
  items: FeedItem[]
  selectedId?: string
  selectedItem?: FeedItem
  onSelect: (id: string) => void
  onStateAction: (id: string, action: ItemStateAction, value: boolean) => void
  onBack?: () => void
  sourceHealth: SourceHealthItem[]
  toolbar?: ReactNode
  loading?: boolean
  error?: string
  actionError?: string
  readonly?: boolean
  isStateActionPending?: (action: ItemStateAction) => boolean
  onRetry?: () => void
  onDismissActionError?: () => void
  onClearFilters?: () => void
}

const emptyState: UserItemState = { is_read: false, is_saved: false, is_later: false, dismissed: false }

const healthLabels = {
  healthy: '正常',
  degraded: '需关注',
  failing: '连续失败',
  unknown: '尚未抓取',
}

const healthTones = {
  healthy: 'positive',
  degraded: 'warning',
  failing: 'critical',
  unknown: 'neutral',
} as const

function SourceMark({ item }: { item: FeedItem }) {
  const label = item.presentation?.source?.name || item.source || item.source_type || '来源'
  const avatarUrl = item.presentation?.source?.avatar_url
  return <Avatar src={avatarUrl || undefined} alt={avatarUrl ? label : undefined} aria-hidden={avatarUrl ? undefined : 'true'} sx={{ width: 34, height: 34, bgcolor: 'primaryContainer', color: 'onPrimaryContainer', fontSize: 14, fontWeight: 750 }}>
    {label.slice(0, 1).toUpperCase()}
  </Avatar>
}

function LoadingStories() {
  return <Stack aria-label="正在读取信息流" spacing={1} sx={{ p: 1.5 }}>
    {Array.from({ length: 8 }, (_, index) => <Stack key={index} direction="row" spacing={1.5} sx={{ minHeight: 82, p: 1.5 }}>
      <Skeleton variant="circular" width={34} height={34} />
      <Box sx={{ flex: 1 }}>
        <Skeleton width="42%" />
        <Skeleton height={28} />
        <Skeleton width="82%" />
      </Box>
    </Stack>)}
  </Stack>
}

export function FeedWorkspace(props: FeedWorkspaceProps) {
  const selected = (props.selectedItem?.id === props.selectedId ? props.selectedItem : undefined)
    ?? props.items.find((item) => item.id === props.selectedId)
    ?? props.items[0]
  const userState = selected?.user_state ?? emptyState
  const health = selected ? resolveItemHealth(selected, props.sourceHealth) : null
  const presentation = selected?.presentation
  const externalUrl = safeExternalUrl(presentation?.links?.canonical_url || selected?.url)
  const sourceUrl = safeExternalUrl(presentation?.links?.source_url)
  const distinctSourceUrl = sourceUrl && sourceUrl !== externalUrl ? sourceUrl : ''
  const selectedSummary = presentation?.analysis?.summary_zh || selected?.summary_zh || ''
  const bodyText = presentation?.content?.body_text || presentation?.content?.excerpt || ''
  const bodyTruncated = presentation?.content?.body_truncated ?? presentation?.content?.excerpt_truncated ?? false
  const bodyCompleteness = presentation?.content?.body_completeness
  const excerptDuplicatesSummary = bodyCompleteness === 'excerpt_only'
    && Boolean(bodyText.trim())
    && bodyText.trim().replace(/\s+/g, ' ') === selectedSummary.trim().replace(/\s+/g, ' ')
  const visibleBody = excerptDuplicatesSummary ? '' : bodyText
  const mediaImages = presentation?.media?.images ?? []
  const selectedTitle = presentation?.content?.title || selected?.title || ''
  const selectedSource = presentation?.source?.name || selected?.source || selected?.source_type || '未知来源'
  const selectedPublishedAt = presentation?.timing?.published_at || selected?.published_at || selected?.fetched_at
  const engagement = presentation?.engagement
  const nativeFacts = engagement ? [
    ['站内分', engagement.native_score],
    ['点赞', engagement.likes],
    ['评论', engagement.comments],
    ['转发', engagement.reposts],
    ['分享', engagement.shares],
    ['赞同率', engagement.upvote_ratio == null ? null : `${Math.round(engagement.upvote_ratio * 100)}%`],
  ].filter((entry): entry is [string, number | string] => entry[1] != null).slice(0, 4) : []
  const [moreAnchor, setMoreAnchor] = useState<HTMLElement | null>(null)
  const hasExplicitSelection = Boolean(props.selectedId)

  function closeMore() {
    setMoreAnchor(null)
  }

  function stateAction(action: ItemStateAction, value: boolean) {
    if (selected) props.onStateAction(selected.id, action, value)
    closeMore()
  }

  function copySummary() {
    if (selected) navigator.clipboard?.writeText(selectedSummary || selectedTitle)
    closeMore()
  }

  return <Box sx={{ height: '100%', minHeight: 0, display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: `${uiLayout.feedListMaxWidth}px minmax(0, 1fr)` }, gap: { xs: 0, md: 1.5 }, p: { xs: 0, md: 1.5 } }}>
    <Surface
      component="section"
      aria-label="信息列表"
      sx={{
        display: { xs: hasExplicitSelection ? 'none' : 'flex', md: 'flex' },
        minWidth: 0,
        minHeight: 0,
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: 'surfaceContainer',
      }}
    >
      <Box component="header" sx={{ p: { xs: 2, md: 2.5 }, pb: 1.5, borderBottom: 1, borderColor: 'divider' }}>
        <Stack direction="row" spacing={2} sx={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Typography component="h1" variant="h3">{props.title}</Typography>
          <Typography variant="caption" color="text.secondary">{props.description}</Typography>
        </Stack>
        {props.toolbar && <Box sx={{ mt: 1.5 }}>{props.toolbar}</Box>}
      </Box>

      <Box data-testid="feed-story-scroll" sx={{ flex: 1, minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain' }}>
        {props.loading && <LoadingStories />}
        {props.error && <Alert severity="error" action={props.onRetry && <Button color="inherit" size="small" onClick={props.onRetry}>重试</Button>} sx={{ m: 2 }}>{props.error}</Alert>}
        {props.actionError && <Alert severity="error" onClose={props.onDismissActionError} sx={{ m: 2 }}>{props.actionError}</Alert>}
        {!props.loading && !props.error && props.items.length === 0 && <EmptyState
          title="没有匹配的信息"
          description="当前筛选条件下没有结果，可以清除筛选后重新查看。"
          actionLabel={props.onClearFilters ? '清除筛选' : undefined}
          onAction={props.onClearFilters}
        />}
        {!props.loading && !props.error && <List disablePadding sx={{ py: 1 }}>
          {props.items.map((item) => {
            const active = selected?.id === item.id
            const read = Boolean(item.user_state?.is_read)
            const itemPresentation = item.presentation
            const sourceName = itemPresentation?.source?.name || item.source || item.source_type || '未知来源'
            const authorName = itemPresentation?.author?.name
            const title = itemPresentation?.content?.title || item.title
            const summary = itemPresentation?.analysis?.summary_zh || item.summary_zh || '暂无概括'
            const thumbnail = item.image_url || itemPresentation?.media?.images?.[0]?.url
            return <ListItem key={item.id} disablePadding>
              <ListItemButton
                data-testid="feed-story"
                selected={active}
                aria-current={active ? 'true' : undefined}
                onClick={() => {
                  props.onSelect(item.id)
                }}
                sx={{ mx: 1, my: 0.5, minHeight: 86, alignItems: 'flex-start', gap: 1.25, px: 1.5, py: 1.25, opacity: read ? 0.74 : 1 }}
              >
                <Badge color="primary" variant="dot" invisible={read} overlap="circular"><SourceMark item={item} /></Badge>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="caption" color="text.secondary" noWrap>{sourceName}{authorName ? ` · ${authorName}` : ''} · {relativeTime(itemPresentation?.timing?.published_at || item.published_at || item.fetched_at)}</Typography>
                  <Typography component="strong" sx={{ display: '-webkit-box', mt: 0.25, overflow: 'hidden', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, fontSize: 14, fontWeight: read ? 550 : 700, lineHeight: 1.35 }}>{title}</Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 0.5, alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ minWidth: 0, flex: 1 }}>{summary}</Typography>
                    <Typography variant="caption" color="primary.main" sx={{ flex: '0 0 auto', fontWeight: 700 }}>{signalText(item)}</Typography>
                  </Stack>
                </Box>
                {thumbnail && <Box
                  component="img"
                  src={thumbnail}
                  alt={`${title} 缩略图`}
                  loading="lazy"
                  sx={{ width: 72, height: 54, flex: '0 0 auto', borderRadius: `${uiRadii.small}px`, objectFit: 'cover', bgcolor: 'surfaceContainerHigh' }}
                />}
              </ListItemButton>
            </ListItem>
          })}
        </List>}
      </Box>
    </Surface>

    <Surface
      component="section"
      aria-label="阅读详情"
      sx={{
        display: { xs: hasExplicitSelection ? 'flex' : 'none', md: 'flex' },
        minWidth: 0,
        minHeight: 0,
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: 'background.paper',
      }}
    >
      {!selected ? <EmptyState title="选择一条信息" description="从左侧列表选择一条信息开始阅读。" /> : <>
        <Box aria-label="文章内容" tabIndex={0} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain' }}>
          <Box component="article" sx={{ width: 'min(100%, 820px)', mx: 'auto', px: { xs: 2, sm: 4, lg: 6 }, py: { xs: 2, md: 4 } }}>
            <Button sx={{ display: { xs: 'inline-flex', md: 'none' }, mb: 2 }} startIcon={<ArrowBackRounded />} onClick={props.onBack}>返回列表</Button>
            <Stack component="header" direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ justifyContent: 'space-between', alignItems: { xs: 'flex-start', sm: 'center' } }}>
              <Stack direction="row" spacing={1.25} sx={{ alignItems: 'center' }}>
                <SourceMark item={selected} />
                <Box>
                  <Typography sx={{ fontWeight: 700 }}>{selectedSource}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {presentation?.author?.name ? `${presentation.author.name} · ` : ''}{selectedPublishedAt ? new Date(selectedPublishedAt).toLocaleString('zh-CN') : '时间未知'}
                  </Typography>
                </Box>
              </Stack>
              <Status
                icon={<RadioRounded />}
                label={`来源健康：${health ? healthLabels[health.status] : '尚未抓取'}`}
                tone={health ? healthTones[health.status] : 'neutral'}
              />
            </Stack>

            <Typography component="h2" variant="h1" sx={{ mt: 3, maxWidth: 760 }}>{selectedTitle}</Typography>
            <Typography sx={{ mt: 2, fontSize: { xs: 16, md: 18 }, lineHeight: 1.8, color: 'text.secondary' }}>
              {selectedSummary || '暂无概括；请打开原文核对完整内容。'}
            </Typography>

            <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 2.5, flexWrap: 'wrap' }}>
              <Status label={signalText(selected)} tone={Number(selected.score ?? 0) >= 8.5 ? 'accent' : 'neutral'} />
              <Status label={presentation?.taxonomy?.channel || selected.channel || selected.category || '未分类频道'} />
              <Status label={presentation?.analysis?.signal_type || selected.signal_type || '未分类类型'} />
              {nativeFacts.map(([label, value]) => <Status key={label} label={`${label} ${value}`} />)}
            </Stack>

            <Divider sx={{ my: 3.5 }} />
            <Box component="section" aria-label="正文片段">
              <Typography color={visibleBody && bodyCompleteness !== 'excerpt_only' ? 'text.primary' : 'text.secondary'} sx={{ lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>
                {visibleBody || (bodyCompleteness === 'excerpt_only'
                  ? '来源暂未提供可保存的全文；当前仅展示上方概括。'
                  : '该条内容未保存正文片段；重新获取来源后可显示。')}
              </Typography>
              {bodyCompleteness === 'excerpt_only' && visibleBody && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25 }}>当前保存的是来源摘要，不是完整正文。</Typography>}
              {bodyTruncated && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.25 }}>内容已截断，打开原文查看完整内容。</Typography>}
            </Box>
            {mediaImages.length > 0 && <Box component="section" aria-label="内容图片" sx={{ mt: 3, display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1.5 }}>
              {mediaImages.map((image) => <Box
                key={image.asset_id}
                component="img"
                src={image.url}
                alt={image.alt}
                loading="lazy"
                sx={{ display: 'block', width: '100%', maxHeight: 520, objectFit: 'contain', borderRadius: `${uiRadii.card}px`, bgcolor: 'surfaceContainer' }}
              />)}
            </Box>}
          </Box>
        </Box>

        <Stack direction="row" spacing={1} useFlexGap sx={{ flex: '0 0 auto', alignItems: 'center', flexWrap: 'wrap', px: { xs: 1.5, md: 3 }, py: 1.5, borderTop: 1, borderColor: 'divider', bgcolor: 'surfaceContainer' }}>
          {externalUrl
            ? <Button component="a" href={externalUrl} target="_blank" rel="noreferrer" variant="contained" startIcon={<OpenInNewRounded />}>打开原文</Button>
            : <Typography color="text.secondary" sx={{ px: 1 }}>原文链接不可用</Typography>}
          {distinctSourceUrl && <Button component="a" href={distinctSourceUrl} target="_blank" rel="noreferrer" variant="outlined">查看原帖</Button>}
          <Button
            variant={userState.is_later ? 'contained' : 'outlined'}
            disabled={props.readonly || props.isStateActionPending?.('is_later')}
            startIcon={userState.is_later ? <BookmarkRounded /> : <BookmarkBorderRounded />}
            onClick={() => stateAction('is_later', !userState.is_later)}
          >{userState.is_later ? '取消稍后读' : '稍后读'}</Button>
          <Button
            variant={userState.is_saved ? 'contained' : 'outlined'}
            disabled={props.readonly || props.isStateActionPending?.('is_saved')}
            startIcon={userState.is_saved ? <StarRounded /> : <StarBorderRounded />}
            onClick={() => stateAction('is_saved', !userState.is_saved)}
          >{userState.is_saved ? '取消收藏' : '收藏'}</Button>
          <Tooltip title="更多操作">
            <IconButton aria-label="更多操作" onClick={(event: MouseEvent<HTMLElement>) => setMoreAnchor(event.currentTarget)} sx={{ ml: 'auto' }}><MoreHorizRounded /></IconButton>
          </Tooltip>
        </Stack>

        <Menu anchorEl={moreAnchor} open={Boolean(moreAnchor)} onClose={closeMore}>
          <MenuItem disabled={props.readonly || props.isStateActionPending?.('is_read')} onClick={() => stateAction('is_read', !userState.is_read)}><CheckRounded sx={{ mr: 1 }} />{userState.is_read ? '标记未读' : '标记已读'}</MenuItem>
          <MenuItem onClick={copySummary}><ContentCopyRounded sx={{ mr: 1 }} />复制摘要</MenuItem>
          <MenuItem disabled={props.readonly || props.isStateActionPending?.('dismissed')} onClick={() => stateAction('dismissed', !userState.dismissed)}><CloseRounded sx={{ mr: 1 }} />{userState.dismissed ? '取消忽略' : '忽略'}</MenuItem>
        </Menu>
      </>}
    </Surface>
  </Box>
}
