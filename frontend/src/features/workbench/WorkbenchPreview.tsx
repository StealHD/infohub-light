import { useMemo, useRef, useState } from 'react'

import {
  Box,
  Avatar,
  Button,
  Chip,
  Divider,
  IconButton,
  InputAdornment,
  NextUiProvider,
  Stack,
  TextField,
  Tooltip,
  Typography,
  nextUiLayout,
  nextUiRadii,
  useMediaQuery,
} from '../../ui'
import {
  CloseRounded,
  ContentCopyRounded,
  HistoryRounded,
  MoreHorizRounded,
  NotificationsNoneRounded,
  OpenInNewRounded,
  RadioRounded,
  SearchRounded,
  SettingsRounded,
  SmartToyRounded,
  StarBorderRounded,
  StarRounded,
  TuneRounded,
} from '../../ui/icons'
import {
  buildWorkbenchHandoffPrompt,
  workbenchPreviewNavigation,
  workbenchPreviewStories,
  type WorkbenchPreviewNavigationItem,
  type WorkbenchPreviewStory,
} from './workbenchPreviewModel'

const navIcons = {
  feed: RadioRounded,
  saved: StarBorderRounded,
  history: HistoryRounded,
  subscriptions: NotificationsNoneRounded,
  agents: SmartToyRounded,
  settings: SettingsRounded,
} satisfies Record<WorkbenchPreviewNavigationItem['id'], typeof RadioRounded>

const stories = workbenchPreviewStories
const navItems = workbenchPreviewNavigation.map((item) => ({ ...item, icon: navIcons[item.id] }))

function WorkbenchNavigation() {
  return <Box
    component="aside"
    sx={{
      display: { xs: 'none', sm: 'flex' },
      minWidth: 0,
      minHeight: 0,
      flexDirection: 'column',
      borderRight: 1,
      borderColor: 'divider',
      bgcolor: 'surfaceContainer',
      backgroundImage: 'linear-gradient(145deg, var(--inteliscope-next-palette-primaryContainer), transparent 42%)',
      overflow: 'hidden',
    }}
  >
    <Stack sx={{ height: nextUiLayout.headerHeight, px: 1.25, justifyContent: 'center', '@media (min-width:1360px)': { px: 2.25 } }}>
      <Typography sx={{ display: 'none', color: 'primary.main', fontWeight: 760, letterSpacing: '-0.025em', '@media (min-width:1360px)': { display: 'block' } }}>Inteliscope</Typography>
      <Typography aria-hidden sx={{ display: 'block', color: 'primary.main', textAlign: 'center', fontWeight: 800, '@media (min-width:1360px)': { display: 'none' } }}>I</Typography>
    </Stack>
    <Stack component="nav" aria-label="工作台导航" spacing={0.5} sx={{ px: 1, py: 1.5 }}>
      {navItems.map(({ label, href, icon: Icon }, index) => <Button
        key={href}
        component="a"
        href={href}
        aria-label={label}
        aria-current={index === 0 ? 'page' : undefined}
        startIcon={<Icon fontSize="small" />}
        sx={{
          minWidth: 0,
          justifyContent: 'center',
          px: 0,
          color: index === 0 ? 'text.primary' : 'text.secondary',
          bgcolor: index === 0 ? 'primaryContainer' : 'transparent',
          '& .MuiButton-startIcon': { m: 0 },
          '&:hover': { bgcolor: index === 0 ? 'primaryContainer' : 'surfaceContainerHigh' },
          '@media (min-width:1360px)': {
            justifyContent: 'flex-start',
            px: 1.25,
            '& .MuiButton-startIcon': { m: '0 10px 0 0' },
          },
        }}
      >
        <Box component="span" sx={{ display: 'none', '@media (min-width:1360px)': { display: 'inline' } }}>{label}</Box>
      </Button>)}
    </Stack>
    <Stack sx={{ mt: 'auto', p: 1, '@media (min-width:1360px)': { p: 1.5 } }}>
      <Button sx={{ minWidth: 0, justifyContent: 'center', color: 'text.secondary', '@media (min-width:1360px)': { justifyContent: 'flex-start' } }}>
        <Avatar sx={{ width: 26, height: 26, bgcolor: 'primaryContainer', color: 'onPrimaryContainer', fontSize: 10, flex: '0 0 auto' }}>IS</Avatar>
        <Box component="span" sx={{ display: 'none', ml: 1, '@media (min-width:1360px)': { display: 'inline' } }}>Inteliscope 用户</Box>
      </Button>
    </Stack>
  </Box>
}

function StoryCard({
  story,
  active,
  expanded,
  saved,
  inContext,
  contextFull,
  onActivate,
  onToggle,
  onToggleSaved,
  onToggleContext,
  registerElement,
}: {
  story: WorkbenchPreviewStory
  active: boolean
  expanded: boolean
  saved: boolean
  inContext: boolean
  contextFull: boolean
  onActivate: () => void
  onToggle: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  registerElement: (element: HTMLElement | null) => void
}) {
  return <Box
    component="article"
    aria-label={story.title}
    ref={registerElement}
    sx={{
      position: 'relative',
      border: 1,
      borderColor: active ? 'outline' : 'outlineVariant',
      borderRadius: `${nextUiRadii.card}px`,
      bgcolor: active ? 'surfaceContainerHigh' : 'background.paper',
      overflow: 'hidden',
      transition: (theme) => theme.transitions.create(['background-color', 'border-color', 'transform'], { duration: theme.transitions.duration.short }),
      '&:hover': { borderColor: 'outline', transform: 'translateY(-1px)' },
      '&::before': active ? {
        content: '""',
        position: 'absolute',
        left: 0,
        top: 18,
        width: 2,
        height: 32,
        bgcolor: 'primary.main',
      } : undefined,
    }}
  >
    <Box
      component="button"
      type="button"
      aria-label={`${expanded ? '收起' : '展开'} ${story.title}`}
      aria-expanded={expanded}
      onClick={() => { onActivate(); onToggle() }}
      sx={{
        width: '100%',
        m: 0,
        p: { xs: 1.75, md: 2 },
        border: 0,
        bgcolor: 'transparent',
        color: 'inherit',
        textAlign: 'left',
      }}
    >
      <Stack direction="row" spacing={1.25} sx={{ alignItems: 'flex-start' }}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography variant="caption" color="text.secondary">{story.age} · {story.source}</Typography>
          <Typography component="h2" variant="h2" sx={{ mt: 0.5 }}>{story.title}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{story.summary}</Typography>
        </Box>
        <MoreHorizRounded fontSize="small" sx={{ color: 'text.secondary', mt: 0.25 }} />
      </Stack>
    </Box>
    {expanded && <Box sx={{ px: { xs: 1.75, md: 2 }, pb: 1.5 }}>
      <Divider sx={{ mb: 1.5 }} />
      <Typography sx={{ color: 'text.secondary' }}>{story.body}</Typography>
    </Box>}
    <Stack direction="row" spacing={0.75} useFlexGap sx={{ px: { xs: 1.75, md: 2 }, pb: 1.5, alignItems: 'center', flexWrap: 'wrap' }}>
      <Chip size="small" label={story.channel} />
      {story.topics.map((topic) => <Chip key={topic} size="small" label={topic} variant="outlined" />)}
      <Button
        size="small"
        variant={saved ? 'contained' : 'text'}
        startIcon={saved ? <StarRounded fontSize="small" /> : <StarBorderRounded fontSize="small" />}
        aria-label={`${saved ? '取消收藏' : '收藏'} ${story.title}`}
        onClick={onToggleSaved}
        sx={{ ml: 'auto' }}
      >{saved ? '已收藏' : '收藏'}</Button>
      <Tooltip title={contextFull && !inContext ? '上下文最多 8 条' : ''}>
        <span>
          <Button
            size="small"
            variant={inContext ? 'contained' : 'text'}
            disabled={contextFull && !inContext}
            startIcon={inContext ? <CloseRounded fontSize="small" /> : <SmartToyRounded fontSize="small" />}
            aria-label={`将 ${story.title} ${inContext ? '移出' : '加入'} Agent 上下文`}
            onClick={onToggleContext}
          >{inContext ? '已加入' : '加入上下文'}</Button>
        </span>
      </Tooltip>
      <IconButton component="a" href="#source" size="small" aria-label={`打开 ${story.title} 原文`}><OpenInNewRounded fontSize="small" /></IconButton>
    </Stack>
  </Box>
}

export function WorkbenchPreview() {
  const wideWorkbench = useMediaQuery('(min-width:1200px)')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [activeId, setActiveId] = useState(stories[1].id)
  const [savedIds, setSavedIds] = useState<string[]>([])
  const [contextIds, setContextIds] = useState<string[]>([])
  const [question, setQuestion] = useState('')
  const [agentOpen, setAgentOpen] = useState(wideWorkbench)
  const [newItemsVisible, setNewItemsVisible] = useState(true)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const cardRefs = useRef(new Map<string, HTMLElement>())
  const visibleStories = useMemo(() => {
    const term = search.trim().toLocaleLowerCase('zh-CN')
    if (!term) return stories
    return stories.filter((story) => [story.title, story.summary, story.source, story.channel, ...story.topics].join(' ').toLocaleLowerCase('zh-CN').includes(term))
  }, [search])
  const contextStories = contextIds.map((id) => stories.find((story) => story.id === id)).filter((story): story is WorkbenchPreviewStory => Boolean(story))

  function toggleContext(id: string) {
    setNotice('')
    setContextIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id)
      if (current.length >= 8) return current
      return [...current, id]
    })
  }

  function jumpTo(story: WorkbenchPreviewStory) {
    setActiveId(story.id)
    cardRefs.current.get(story.id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  async function copyHandoff() {
    if (!contextStories.length) return
    try {
      await navigator.clipboard.writeText(buildWorkbenchHandoffPrompt(question, contextStories))
      setNotice('交接提示词已复制')
    } catch {
      setNotice('无法写入剪贴板，请手动复制')
    }
  }

  return <NextUiProvider>
    <Box
      component="main"
      sx={{
        height: '100dvh',
        minWidth: 320,
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr)',
        bgcolor: 'background.default',
        color: 'text.primary',
        overflow: 'hidden',
        '@media (min-width:768px)': { gridTemplateColumns: `${nextUiLayout.compactSidebarWidth}px minmax(0, 1fr)` },
        '@media (min-width:1200px)': { gridTemplateColumns: `${nextUiLayout.compactSidebarWidth}px minmax(640px, 1fr) ${agentOpen ? nextUiLayout.agentPanelWidth : nextUiLayout.collapsedAgentWidth}px` },
        '@media (min-width:1360px)': { gridTemplateColumns: `${nextUiLayout.desktopSidebarWidth}px minmax(640px, 1fr) ${agentOpen ? nextUiLayout.agentPanelWidth : nextUiLayout.collapsedAgentWidth}px` },
        transition: (theme) => theme.transitions.create('grid-template-columns', { duration: theme.transitions.duration.standard }),
      }}
    >
      <WorkbenchNavigation />

      <Box sx={{ gridColumn: { xs: 1, sm: 2 }, minWidth: 0, minHeight: 0, display: 'grid', gridTemplateRows: `${nextUiLayout.headerHeight}px minmax(0, 1fr)`, borderColor: 'divider', '@media (min-width:1200px)': { borderRight: 1 } }}>
        <Stack component="header" direction="row" spacing={1.25} sx={{ px: { xs: 1.25, md: 2 }, alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
          <Typography component="h1" sx={{ fontWeight: 720, flex: '0 0 auto' }}>信息流</Typography>
          <TextField
            hiddenLabel
            size="small"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索信息流"
            slotProps={{ htmlInput: { 'aria-label': '搜索信息流' }, input: { startAdornment: <InputAdornment position="start"><SearchRounded fontSize="small" /></InputAdornment> } }}
            sx={{ width: 'min(360px, 48vw)', ml: 'auto !important', '& .MuiOutlinedInput-root': { bgcolor: 'surfaceContainer' } }}
          />
          <Tooltip title="筛选来源、频道、主题和最低分">
            <IconButton aria-label="筛选信息流"><TuneRounded fontSize="small" /></IconButton>
          </Tooltip>
          <Chip label="全部" color="primary" variant="outlined" />
          <Button component="a" href="/__preview/workbench-heroui" size="small" aria-label="切换到 HeroUI 版">HeroUI</Button>
          <Tooltip title={agentOpen ? '收起 Agent 面板' : '展开 Agent 面板'}>
            <IconButton aria-label={agentOpen ? '收起 Agent 面板' : '展开 Agent 面板'} aria-expanded={agentOpen} onClick={() => setAgentOpen((value) => !value)}><SmartToyRounded fontSize="small" /></IconButton>
          </Tooltip>
        </Stack>

        <Box data-testid="workbench-feed-scroll" sx={{ position: 'relative', minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain', scrollBehavior: 'smooth' }}>
          <Box sx={{ width: 'min(100%, 920px)', mx: 'auto', px: { xs: 1.25, md: 2.5 }, py: 2.5, display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: '28px minmax(0, 1fr)' }, gap: { xs: 0, md: 1.5 } }}>
            <Stack component="nav" aria-label="信息流进度" spacing={0.65} sx={{ display: { xs: 'none', md: 'flex' }, position: 'sticky', top: 110, height: 112, justifyContent: 'center', alignItems: 'flex-start' }}>
              {stories.map((story, index) => {
                const active = story.id === activeId
                return <Box
                  key={story.id}
                  component="button"
                  type="button"
                  aria-label={`跳转到第 ${index + 1} 条信息`}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => jumpTo(story)}
                  sx={{ width: active ? 26 : index % 3 === 0 ? 18 : 11, height: 2, minHeight: 2, p: 0, border: 0, borderRadius: `${nextUiRadii.small}px`, bgcolor: active ? 'primary.main' : 'outline', opacity: active ? 1 : 0.65, transition: (theme) => theme.transitions.create(['width', 'background-color'], { duration: theme.transitions.duration.shortest }) }}
                />
              })}
            </Stack>
            <Stack spacing={1.25} sx={{ minWidth: 0 }}>
              <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', px: 0.5 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">私人情报工作台</Typography>
                  <Typography variant="body2" color="text.secondary">旧内容在上，最新内容在下 · {visibleStories.length} 条</Typography>
                </Box>
                <Typography variant="caption" color="text.secondary">更新于刚刚</Typography>
              </Stack>
              {visibleStories.map((story) => <StoryCard
                key={story.id}
                story={story}
                active={story.id === activeId}
                expanded={story.id === expandedId}
                saved={savedIds.includes(story.id)}
                inContext={contextIds.includes(story.id)}
                contextFull={contextIds.length >= 8}
                onActivate={() => setActiveId(story.id)}
                onToggle={() => setExpandedId((current) => current === story.id ? null : story.id)}
                onToggleSaved={() => setSavedIds((current) => current.includes(story.id) ? current.filter((id) => id !== story.id) : [...current, story.id])}
                onToggleContext={() => toggleContext(story.id)}
                registerElement={(element) => { if (element) cardRefs.current.set(story.id, element); else cardRefs.current.delete(story.id) }}
              />)}
              {!visibleStories.length && <Stack sx={{ py: 8, alignItems: 'center' }}><Typography color="text.secondary">没有匹配的信息</Typography><Button onClick={() => setSearch('')}>清除搜索</Button></Stack>}
            </Stack>
          </Box>
          {newItemsVisible && <Button
            type="button"
            variant="contained"
            aria-label="查看 2 条新内容"
            onClick={() => { setNewItemsVisible(false); jumpTo(stories[stories.length - 1]) }}
            sx={{ position: 'sticky', left: '50%', bottom: 18, transform: 'translateX(-50%)', zIndex: 2 }}
          >2 条新内容</Button>}
        </Box>
      </Box>

      <Box
        component="aside"
        aria-label="OpenClaw 上下文"
        sx={{
          position: 'fixed',
          zIndex: 12,
          inset: '0 0 0 auto',
          width: `min(${nextUiLayout.agentPanelWidth}px, 100vw)`,
          minWidth: 0,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          bgcolor: 'surfaceContainer',
          borderLeft: 1,
          borderColor: 'divider',
          transform: agentOpen ? 'translateX(0)' : 'translateX(100%)',
          overflow: 'hidden',
          transition: (theme) => theme.transitions.create(['transform', 'width'], { duration: theme.transitions.duration.standard }),
          '@media (min-width:1200px)': {
            position: 'relative',
            zIndex: 'auto',
            inset: 'auto',
            gridColumn: 3,
            width: 'auto',
            transform: 'none',
          },
        }}
      >
        <Stack direction="row" spacing={1} sx={{ height: nextUiLayout.headerHeight, px: 1.5, alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
          <SmartToyRounded fontSize="small" color="primary" />
          {agentOpen && <><Typography sx={{ minWidth: 0, flex: 1, fontWeight: 680 }} noWrap>OpenClaw 上下文</Typography><Chip size="small" label="已配置" variant="outlined" /><IconButton aria-label="收起 Agent 面板" aria-expanded="true" size="small" onClick={() => setAgentOpen(false)}><CloseRounded fontSize="small" /></IconButton></>}
        </Stack>
        {agentOpen && <>
          <Stack spacing={1.25} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', p: 1.5 }}>
            <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}><Typography variant="caption" color="text.secondary">已选上下文</Typography><Typography variant="caption" color="text.secondary">{contextIds.length} / 8</Typography></Stack>
            {!contextStories.length && <Stack sx={{ minHeight: 150, px: 2, justifyContent: 'center', alignItems: 'center', textAlign: 'center', border: 1, borderStyle: 'dashed', borderColor: 'outlineVariant', borderRadius: `${nextUiRadii.card}px` }}><SmartToyRounded sx={{ color: 'text.secondary', mb: 1 }} /><Typography variant="body2" color="text.secondary">从信息卡片加入内容，整理后交给本地 OpenClaw。</Typography></Stack>}
            {contextStories.map((story, index) => <Stack key={story.id} direction="row" spacing={1} sx={{ p: 1.25, border: 1, borderColor: 'outlineVariant', borderRadius: `${nextUiRadii.card}px`, bgcolor: 'background.paper', alignItems: 'flex-start' }}>
              <Typography variant="caption" color="primary.main">{String(index + 1).padStart(2, '0')}</Typography>
              <Box sx={{ minWidth: 0, flex: 1 }}><Typography variant="body2" sx={{ fontWeight: 620 }}>{story.title}</Typography><Typography variant="caption" color="text.secondary">{story.source}</Typography></Box>
              <IconButton size="small" aria-label={`从上下文移除 ${story.title}`} onClick={() => toggleContext(story.id)}><CloseRounded fontSize="small" /></IconButton>
            </Stack>)}
          </Stack>
          <Stack spacing={1} sx={{ p: 1.5, borderTop: 1, borderColor: 'divider' }}>
            <TextField
              multiline
              minRows={3}
              maxRows={6}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="例如：提炼这些信息中的产品机会"
              slotProps={{ htmlInput: { 'aria-label': '交给 OpenClaw 的问题', maxLength: 1200 } }}
              sx={{ '& .MuiOutlinedInput-root': { bgcolor: 'background.paper' } }}
            />
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography role="status" variant="caption" color={notice.includes('无法') ? 'error.main' : 'text.secondary'} sx={{ minWidth: 0, flex: 1 }}>{notice || '仅生成交接提示词，不在站内运行 Agent'}</Typography>
              <Button variant="contained" disabled={!contextStories.length} startIcon={<ContentCopyRounded fontSize="small" />} onClick={() => void copyHandoff()}>复制并交给 OpenClaw</Button>
            </Stack>
          </Stack>
        </>}
      </Box>

      <Stack component="nav" aria-label="移动端主导航" direction="row" sx={{ display: { xs: 'flex', sm: 'none' }, position: 'fixed', zIndex: 10, left: 0, right: 0, bottom: 0, height: nextUiLayout.mobileNavHeight, bgcolor: 'surfaceContainer', borderTop: 1, borderColor: 'divider', justifyContent: 'space-around', alignItems: 'center' }}>
        {navItems.slice(0, 4).map(({ label, href, icon: Icon }) => <IconButton key={href} component="a" href={href} aria-label={label} sx={{ width: 44, height: 44 }}><Icon fontSize="small" /></IconButton>)}
      </Stack>
    </Box>
  </NextUiProvider>
}
