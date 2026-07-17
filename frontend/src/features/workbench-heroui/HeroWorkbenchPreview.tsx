import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  Card,
  Chip,
  ScrollShadow,
  SearchField,
  Separator,
  TextArea,
  Tooltip,
} from '@heroui/react'
import {
  Bell,
  Bookmark,
  BookmarkCheck,
  Bot,
  Copy,
  ExternalLink,
  History,
  PanelRightClose,
  PanelRightOpen,
  Radio,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Star,
  X,
  type LucideIcon,
} from 'lucide-react'

import {
  buildWorkbenchHandoffPrompt,
  fixedPreviewFixtureMarker,
  workbenchPreviewNavigation,
  workbenchPreviewStories,
  type WorkbenchPreviewNavigationItem,
  type WorkbenchPreviewStory,
} from './workbenchPreviewModel'
import './heroui-workbench.css'

const navigationIcons = {
  feed: Radio,
  saved: Star,
  history: History,
  subscriptions: Bell,
  agents: Bot,
  settings: Settings,
} satisfies Record<WorkbenchPreviewNavigationItem['id'], LucideIcon>

const stories = workbenchPreviewStories

function initialDesktopAgentState() {
  return typeof window !== 'undefined' && window.matchMedia('(min-width: 1200px)').matches
}

function HeroNavigation() {
  return <aside className="hero-navigation">
    <div className="hero-navigation__brand">
      <span className="hero-navigation__brand-full">Inteliscope</span>
      <span className="hero-navigation__brand-mark" aria-hidden="true">I</span>
    </div>
    <nav aria-label="工作台导航" className="hero-navigation__links">
      {workbenchPreviewNavigation.map((item, index) => {
        const Icon = navigationIcons[item.id]
        return <a
          key={item.id}
          href={item.href}
          aria-label={item.label}
          aria-current={index === 0 ? 'page' : undefined}
          className={`hero-navigation__link${index === 0 ? ' hero-navigation__link--active' : ''}`}
        >
          <Icon size={17} strokeWidth={1.75} aria-hidden="true" />
          <span>{item.label}</span>
        </a>
      })}
    </nav>
    <Button className="hero-navigation__account" variant="ghost" aria-label="账户 Inteliscope 用户">
      <Avatar size="sm" color="accent">
        <Avatar.Fallback>IS</Avatar.Fallback>
      </Avatar>
      <span>Inteliscope 用户</span>
    </Button>
  </aside>
}

function HeroStoryCard({
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
  return <Card
    role="article"
    aria-label={story.title}
    data-testid="hero-story-card"
    data-active={active ? 'true' : 'false'}
    ref={registerElement}
    variant={active ? 'tertiary' : 'secondary'}
    className="hero-story"
  >
    <button
      type="button"
      className="hero-story__summary-button"
      aria-label={`${expanded ? '收起' : '展开'} ${story.title}`}
      aria-expanded={expanded}
      onClick={() => { onActivate(); onToggle() }}
    >
      <span className="hero-story__eyebrow">{story.age}<span aria-hidden="true"> · </span>{story.source}</span>
      <Card.Title className="hero-story__title">{story.title}</Card.Title>
      <Card.Description className="hero-story__summary">{story.summary}</Card.Description>
    </button>
    {expanded && <Card.Content className="hero-story__body">
      <Separator />
      <p>{story.body}</p>
    </Card.Content>}
    <Card.Footer className="hero-story__footer">
      <div className="hero-story__tags" aria-label="频道和主题">
        <Chip size="sm" color="accent" variant="soft"><Chip.Label>{story.channel}</Chip.Label></Chip>
        {story.topics.map((topic) => <Chip key={topic} size="sm" variant="soft"><Chip.Label>{topic}</Chip.Label></Chip>)}
      </div>
      <div className="hero-story__actions">
        <Button
          size="sm"
          variant={saved ? 'secondary' : 'ghost'}
          aria-label={`${saved ? '取消收藏' : '收藏'} ${story.title}`}
          onPress={onToggleSaved}
        >
          {saved ? <BookmarkCheck size={15} aria-hidden="true" /> : <Bookmark size={15} aria-hidden="true" />}
          <span>{saved ? '已收藏' : '收藏'}</span>
        </Button>
        <Button
          size="sm"
          variant={inContext ? 'secondary' : 'ghost'}
          isDisabled={contextFull && !inContext}
          aria-label={`将 ${story.title} ${inContext ? '移出' : '加入'} Agent 上下文`}
          onPress={onToggleContext}
        >
          {inContext ? <X size={15} aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}
          <span>{inContext ? '已加入' : '加入上下文'}</span>
        </Button>
        <a className="hero-story__source-link" href="#source" aria-label={`打开 ${story.title} 原文`}>
          <ExternalLink size={15} aria-hidden="true" />
        </a>
      </div>
    </Card.Footer>
  </Card>
}

export function HeroWorkbenchPreview() {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [activeId, setActiveId] = useState(stories[1].id)
  const [savedIds, setSavedIds] = useState<string[]>([])
  const [contextIds, setContextIds] = useState<string[]>([])
  const [question, setQuestion] = useState('')
  const [agentOpen, setAgentOpen] = useState(initialDesktopAgentState)
  const [newItemsVisible, setNewItemsVisible] = useState(true)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const cardRefs = useRef(new Map<string, HTMLElement>())
  const agentToggleRef = useRef<HTMLButtonElement>(null)

  const closeAgentAndRestoreFocus = useCallback(() => {
    setAgentOpen(false)
    window.requestAnimationFrame(() => agentToggleRef.current?.focus())
  }, [])

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1200px)')
    const handleChange = (event: MediaQueryListEvent) => setAgentOpen(event.matches)
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    if (!agentOpen) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeAgentAndRestoreFocus()
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [agentOpen, closeAgentAndRestoreFocus])

  const visibleStories = useMemo(() => {
    const term = search.trim().toLocaleLowerCase('zh-CN')
    if (!term) return stories
    return stories.filter((story) => [story.title, story.summary, story.source, story.channel, ...story.topics]
      .join(' ')
      .toLocaleLowerCase('zh-CN')
      .includes(term))
  }, [search])

  const contextStories = contextIds
    .map((id) => stories.find((story) => story.id === id))
    .filter((story): story is WorkbenchPreviewStory => Boolean(story))

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

  return <main className="hero-workbench dark" data-fixed-preview-fixture={fixedPreviewFixtureMarker} data-theme="dark" data-ui-system="heroui">
    <HeroNavigation />

    <section className="hero-feed-column" aria-label="信息流工作区">
      <header className="hero-toolbar">
        <div className="hero-toolbar__title-row"><h1>信息流</h1></div>
        <SearchField
          aria-label="搜索信息流"
          value={search}
          onChange={setSearch}
          className="hero-search"
          fullWidth
          variant="secondary"
        >
          <SearchField.Group>
            <SearchField.SearchIcon><Search /></SearchField.SearchIcon>
            <SearchField.Input placeholder="搜索标题、来源或主题" />
            <SearchField.ClearButton aria-label="清除搜索" />
          </SearchField.Group>
        </SearchField>
        <Tooltip delay={300}>
          <Tooltip.Trigger aria-label="筛选说明" className="hero-filter-trigger">
            <SlidersHorizontal size={17} aria-hidden="true" />
          </Tooltip.Trigger>
          <Tooltip.Content>来源、频道、主题与最低分</Tooltip.Content>
        </Tooltip>
        <Chip size="sm" color="accent" variant="soft"><Chip.Label>全部</Chip.Label></Chip>
        <Button
          ref={agentToggleRef}
          size="sm"
          variant="ghost"
          isIconOnly
          aria-label={agentOpen ? '收起 Agent 面板' : '展开 Agent 面板'}
          aria-expanded={agentOpen}
          aria-controls="hero-agent-panel"
          onPress={() => setAgentOpen((value) => !value)}
        >
          {agentOpen ? <PanelRightClose size={17} aria-hidden="true" /> : <PanelRightOpen size={17} aria-hidden="true" />}
        </Button>
      </header>

      <ScrollShadow
        data-testid="hero-feed-scroll"
        className="hero-feed-scroll"
        orientation="vertical"
        size={32}
      >
        <div className="hero-feed-shell">
          <nav aria-label="信息流进度" className="hero-progress-rail">
            {stories.map((story, index) => <button
              key={story.id}
              type="button"
              aria-label={`跳转到第 ${index + 1} 条信息`}
              aria-current={story.id === activeId ? 'true' : undefined}
              data-major={index % 3 === 0 ? 'true' : 'false'}
              onClick={() => jumpTo(story)}
            />)}
          </nav>
          <div className="hero-feed-list">
            <div className="hero-feed-meta">
              <div>
                <span>私人情报工作台</span>
                <p>旧内容在上，最新内容在下 · {visibleStories.length} 条</p>
              </div>
              <time>更新于刚刚</time>
            </div>

            {visibleStories.map((story) => <HeroStoryCard
              key={story.id}
              story={story}
              active={story.id === activeId}
              expanded={story.id === expandedId}
              saved={savedIds.includes(story.id)}
              inContext={contextIds.includes(story.id)}
              contextFull={contextIds.length >= 8}
              onActivate={() => setActiveId(story.id)}
              onToggle={() => setExpandedId((current) => current === story.id ? null : story.id)}
              onToggleSaved={() => setSavedIds((current) => current.includes(story.id)
                ? current.filter((id) => id !== story.id)
                : [...current, story.id])}
              onToggleContext={() => toggleContext(story.id)}
              registerElement={(element) => {
                if (element) cardRefs.current.set(story.id, element)
                else cardRefs.current.delete(story.id)
              }}
            />)}

            {!visibleStories.length && <Card variant="transparent" className="hero-empty-state">
              <Card.Title>没有匹配的信息</Card.Title>
              <Card.Description>换一个关键词，或清除当前搜索。</Card.Description>
              <Button size="sm" variant="secondary" onPress={() => setSearch('')}>清除搜索</Button>
            </Card>}
          </div>
        </div>

        {newItemsVisible && <Button
          className="hero-new-items"
          size="sm"
          aria-label="查看 2 条新内容"
          onPress={() => {
            setNewItemsVisible(false)
            jumpTo(stories[stories.length - 1])
          }}
        >2 条新内容</Button>}
      </ScrollShadow>
    </section>

    <aside
      id="hero-agent-panel"
      aria-label="OpenClaw 上下文"
      className="hero-agent"
      data-open={agentOpen ? 'true' : 'false'}
    >
      <header className="hero-agent__header">
        <Sparkles size={17} aria-hidden="true" />
        {agentOpen && <>
          <strong>OpenClaw 上下文</strong>
          <Chip size="sm" variant="soft" color="accent"><Chip.Label>已配置</Chip.Label></Chip>
          <Button
            size="sm"
            variant="ghost"
            isIconOnly
            aria-label="关闭 Agent 面板"
            onPress={closeAgentAndRestoreFocus}
          ><X size={17} aria-hidden="true" /></Button>
        </>}
      </header>

      {agentOpen && <>
        <ScrollShadow className="hero-agent__context" orientation="vertical" size={24}>
          <div className="hero-agent__section-title"><span>已选上下文</span><span>{contextIds.length} / 8</span></div>
          {!contextStories.length && <Card variant="transparent" className="hero-agent__empty">
            <Sparkles size={20} aria-hidden="true" />
            <Card.Description>从信息卡片加入内容，整理后交给本地 OpenClaw。</Card.Description>
          </Card>}
          {contextStories.map((story, index) => <Card key={story.id} variant="secondary" className="hero-context-card">
            <span className="hero-context-card__index">{String(index + 1).padStart(2, '0')}</span>
            <div>
              <Card.Title>{story.title}</Card.Title>
              <Card.Description>{story.source}</Card.Description>
            </div>
            <Button
              size="sm"
              variant="ghost"
              isIconOnly
              aria-label={`移除 ${story.title}`}
              onPress={() => toggleContext(story.id)}
            ><X size={15} aria-hidden="true" /></Button>
          </Card>)}
        </ScrollShadow>
        <div className="hero-agent__composer">
          <TextArea
            fullWidth
            variant="secondary"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            aria-label="交给 OpenClaw 的问题"
            placeholder="例如：提炼这些信息中的产品机会"
            maxLength={1200}
            rows={4}
          />
          <div className="hero-agent__handoff">
            <span role="status" data-error={notice.includes('无法') ? 'true' : 'false'}>
              {notice || '仅生成交接提示词，不在站内运行 Agent'}
            </span>
            <Button
              size="sm"
              isDisabled={!contextStories.length}
              aria-label="复制并交给 OpenClaw"
              onPress={() => void copyHandoff()}
            ><Copy size={15} aria-hidden="true" />复制交接</Button>
          </div>
        </div>
      </>}
    </aside>

    <nav aria-label="移动端主导航" className="hero-mobile-navigation">
      {workbenchPreviewNavigation.slice(0, 4).map((item) => {
        const Icon = navigationIcons[item.id]
        return <a key={item.id} href={item.href} aria-label={item.label}><Icon size={19} aria-hidden="true" /><span>{item.label}</span></a>
      })}
    </nav>
  </main>
}
