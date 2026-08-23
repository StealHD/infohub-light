import { useId, useMemo, type Key } from 'react'

import { Header, Icons, ListBox, Select } from '../../../design-system'
import type { OpenClawChatController, OpenClawModelOption } from '../openclawContracts'
import { OpenClawContextUsageIndicator } from './OpenClawMessageViews'

type ChatController = OpenClawChatController

function formatContextWindow(value?: number): string {
  if (!value) return ''
  if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}M 上下文`
  if (value >= 1000) return `${Math.round(value / 1000)}k 上下文`
  return `${value} 上下文`
}

function formatModelThinking(model: OpenClawModelOption): string {
  if (model.reasoning === false) return '不支持思考档位'
  if (model.thinkingLevels?.length) return `思考：${model.thinkingLevels.map((option) => option.label).join('、')}`
  return ''
}

function formatModelCapabilities(model: OpenClawModelOption): string {
  return [formatContextWindow(model.contextWindow), model.supportsImages ? '支持图片' : '', formatModelThinking(model)].filter(Boolean).join(' · ')
}

const AUTO_THINKING_KEY = '__auto__'

function groupModelsByProvider(models: OpenClawModelOption[]) {
  const groups: Array<{ provider: string; models: OpenClawModelOption[] }> = []
  const byProvider = new Map<string, OpenClawModelOption[]>()
  for (const model of models) {
    const existing = byProvider.get(model.provider)
    if (existing) {
      existing.push(model)
      continue
    }
    const providerModels = [model]
    byProvider.set(model.provider, providerModels)
    groups.push({ provider: model.provider, models: providerModels })
  }
  return groups
}

export function OpenClawRuntimeControls({ chat }: { chat: ChatController }) {
  const thinkingDescriptionId = useId()
  const currentModel = chat.models.find((model) => model.id === chat.runtimeSelection.modelId)
  const currentThinking = chat.thinkingOptions.find((option) => option.id === chat.runtimeSelection.thinkingLevel)
  const modelGroups = useMemo(() => groupModelsByProvider(chat.models), [chat.models])
  const controlsDisabled = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading
  const modelDisabled = controlsDisabled || !chat.models.length
  const thinkingUnavailableReason = !currentModel
    ? '尚未取得当前模型信息。'
    : currentModel.reasoning === false
      ? '此模型未提供推理档位。'
      : !chat.thinkingOptions.length
        ? 'OpenClaw 未返回此模型的可选推理档位。'
        : ''
  const thinkingDisabled = controlsDisabled || Boolean(thinkingUnavailableReason)
  const modelLabel = currentModel?.name ?? (chat.runtimeLoading ? '正在读取模型…' : 'OpenClaw 当前设置')
  const thinkingLabel = currentThinking?.label ?? '自动'
  const thinkingItems: Array<{ id: string; label: string; description?: string }> = [
    {
      id: AUTO_THINKING_KEY,
      label: '自动',
      description: thinkingUnavailableReason || '使用 OpenClaw 默认设置',
    },
    ...(thinkingUnavailableReason
      ? []
      : chat.thinkingOptions.map((option) => ({ ...option, description: undefined }))),
  ]

  return <div
    data-testid="openclaw-runtime-controls"
    className="flex min-w-0 items-center gap-1 overflow-hidden"
  >
    <OpenClawContextUsageIndicator usage={chat.contextUsage} />

    <Select
      aria-label={`OpenClaw 模型：${modelLabel}`}
      selectedKey={chat.runtimeSelection.modelId ?? undefined}
      onSelectionChange={(key: Key | null) => {
        if (key === null || String(key) === chat.runtimeSelection.modelId) return
        void chat.setModel(String(key))
      }}
      isDisabled={modelDisabled}
      className="w-fit min-w-0 max-w-[180px] shrink overflow-hidden"
    >
      <Select.Trigger
        aria-label={`OpenClaw 模型：${modelLabel}`}
        className={`type-control flex min-h-8 w-fit min-w-0 max-w-[180px] items-center gap-1 overflow-hidden rounded-lg border-0 bg-default/80 px-2 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${modelDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
      >
        <span className="min-w-0 flex-1 truncate">{modelLabel}</span>
        <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
      </Select.Trigger>
      <Select.Popover placement="top start" offset={8} className="z-50 max-h-[min(360px,calc(100dvh-24px))] w-[min(280px,calc(100vw-24px))] overflow-hidden">
        <ListBox aria-label="OpenClaw 模型" className="max-h-[min(360px,calc(100dvh-24px))] overflow-y-auto overscroll-contain">
          {modelGroups.map((group) => <ListBox.Section key={group.provider} id={`provider:${group.provider}`}>
            <Header className="type-label px-2 py-1.5 text-muted">{group.provider}</Header>
            {group.models.map((model) => <ListBox.Item
              key={model.id}
              id={model.id}
              textValue={`${model.provider} ${model.name}`}
              className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px] items-center gap-2"
            >
              <span className="min-w-0">
                <span className="type-control block min-w-0 truncate">{model.name}</span>
                {formatModelCapabilities(model) && <span className="type-meta block min-w-0 truncate text-muted">
                  {formatModelCapabilities(model)}
                </span>}
              </span>
              <ListBox.ItemIndicator className="text-accent" />
            </ListBox.Item>)}
          </ListBox.Section>)}
        </ListBox>
      </Select.Popover>
    </Select>

    <div className="shrink-0" title={thinkingUnavailableReason || undefined}>
      <Select
        aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
        selectedKey={chat.runtimeSelection.thinkingLevel ?? AUTO_THINKING_KEY}
        onSelectionChange={(key: Key | null) => {
          if (key === null) return
          const next = String(key) === AUTO_THINKING_KEY ? null : String(key)
          if (next === chat.runtimeSelection.thinkingLevel) return
          void chat.setThinking(next)
        }}
        isDisabled={thinkingDisabled}
        className="min-w-0"
      >
        <Select.Trigger
          aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
          aria-describedby={thinkingUnavailableReason ? thinkingDescriptionId : undefined}
          className={`type-control flex min-h-8 shrink-0 items-center gap-1 rounded-lg border-0 bg-default/80 px-2 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${thinkingDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
        >
          <span>{thinkingLabel}</span>
          <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
        </Select.Trigger>
        <Select.Popover placement="top end" offset={8} className="z-50 w-[min(220px,calc(100vw-24px))]">
          <ListBox aria-label="OpenClaw 思考程度">
            <ListBox.Section id="thinking-options">
              <Header className="type-label px-2 py-1.5 text-muted">
                {currentModel ? `${currentModel.provider} · ${currentModel.name}` : '当前模型'}
              </Header>
              {thinkingItems.map((option) => <ListBox.Item key={option.id} id={option.id} textValue={option.label} className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px] items-center gap-2">
                <span className="min-w-0">
                  <span className="type-control block">{option.label}</span>
                  {option.description && <span className="type-meta block text-muted">{option.description}</span>}
                </span>
                <ListBox.ItemIndicator className="text-accent" />
              </ListBox.Item>)}
            </ListBox.Section>
          </ListBox>
        </Select.Popover>
      </Select>
      {thinkingUnavailableReason && <span id={thinkingDescriptionId} className="sr-only">{thinkingUnavailableReason}</span>}
    </div>
  </div>
}
