import { useRef, useState } from 'react'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { Button, Icons, Popover, RefreshButton } from '../../design-system'
import { EffortModelList } from '../../design-system/EffortModelList'
import { EffortSlider } from '../../design-system/EffortSlider'
import { useModelRefresh } from './useModelRefresh'

function sourceOf(id: string) { return id.includes('/') ? id.slice(0, id.indexOf('/')) : id }

export function InformationModelFields({ value, onChange, disabled, compactHeading = false }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void; disabled: boolean; compactHeading?: boolean
}) {
  const { models, refresh, refreshing, message, error } = useModelRefresh()
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'effort' | 'model'>('effort')
  const [preview, setPreview] = useState<number | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const modelRef = useRef<HTMLButtonElement>(null)
  const selectedModel = models.data?.models.find((model) => model.id === value.model?.id)
  const source = selectedModel && sourceOf(selectedModel.id)
  const modelName = selectedModel ? selectedModel.name === selectedModel.id ? selectedModel.name : `${source} · ${selectedModel.name}` : value.model?.id || '选择模型'
  const levels = selectedModel?.thinking_levels || []
  const labels = ['模型默认', ...levels]
  const selected = value.model?.thinking ? levels.indexOf(value.model.thinking) + 1 : 0
  const index = Math.max(0, preview ?? selected)
  const thinkingName = value.model?.thinking && !levels.includes(value.model.thinking) ? '需重新选择' : labels[index]
  const chooserDisabled = disabled || models.data?.status !== 'ready' || !models.data.models.length
  const status = models.isPending ? '正在加载模型目录…'
    : models.isError ? '模型目录加载失败，请刷新重试。'
    : models.data?.status === 'unavailable' ? '尚未读取模型目录；请刷新重试。'
    : models.data?.status === 'stale' ? '模型目录已过期，请刷新。'
    : !models.data?.models.length ? '当前没有可用模型，请检查模型配置后刷新。'
    : value.model && !selectedModel ? '所选模型已不可用，请重新选择。'
    : value.model?.thinking && !levels.includes(value.model.thinking) ? '所选推理强度已不可用，请重新选择。' : ''
  function close() { setOpen(false); setView('effort'); setPreview(null); requestAnimationFrame(() => triggerRef.current?.focus()) }
  return <fieldset className="grid gap-3">{!compactHeading && <legend className="type-section-title">模型</legend>}
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="type-control">分析模型</p>
      <RefreshButton pending={refreshing || models.isFetching} aria-label="刷新模型目录" onPress={refresh} /></div>
    <div className="grid gap-2"><p className="type-control">选择模型与推理强度</p>
      <Popover isOpen={open} onOpenChange={(next) => { setOpen(next); if (!next) { setView('effort'); setPreview(null) } }}>
        <Button ref={triggerRef} variant="ghost" className="effort-picker-trigger type-control" aria-label={`选择模型：${modelName}，推理强度：${thinkingName}`} isDisabled={chooserDisabled}>
          <span className="effort-toolbar-model">{modelName}</span><span className="effort-toolbar-level">{selectedModel ? thinkingName : ''}</span><Icons.ChevronDown size={15} aria-hidden="true" />
        </Button>
        <Popover.Content placement="top start" offset={8} containerPadding={12} className="effort-picker-surface">
          <Popover.Dialog aria-label="自动化模型与推理强度" className="p-0"><div className="effort-picker-dialog" onKeyDownCapture={(event) => {
            if (event.key !== 'Escape') return
            event.preventDefault(); event.stopPropagation(); close()
          }}>
            {view === 'model' ? <><Button isIconOnly size="sm" variant="ghost" className="effort-model-back" aria-label="返回推理强度" onPress={() => { setView('effort'); requestAnimationFrame(() => modelRef.current?.focus()) }}><Icons.ChevronLeft size={15} aria-hidden="true" /></Button>
              <EffortModelList label="自动化模型" selectedId={value.model?.id || null} disabled={disabled}
                models={(models.data?.models || []).map((model) => ({ id: model.id, name: model.name, source: sourceOf(model.id) }))}
                onSelect={(id) => { if (id !== value.model?.id) onChange({ ...value, model: { id, thinking: null } }); close() }} />
            </> : <><div className="effort-picker-heading"><span aria-hidden="true" />
              <Button ref={modelRef} variant="ghost" className="effort-model-trigger type-body" aria-label={`选择模型：${modelName}`} isDisabled={chooserDisabled} onPress={() => setView('model')}>
                <span className="effort-picker-value type-control">{thinkingName}<Icons.ChevronRight size={12} aria-hidden="true" /></span>
                <span className="effort-picker-model-name type-meta">{modelName}</span>
              </Button>
              <Button isIconOnly size="sm" variant="ghost" className="effort-reset-button" aria-label="恢复模型默认推理强度" isDisabled={disabled || !selectedModel || !value.model?.thinking} onPress={() => { if (selectedModel) onChange({ ...value, model: { id: selectedModel.id, thinking: null } }) }}><Icons.RotateCcw size={15} aria-hidden="true" /></Button>
            </div>
              <EffortSlider labels={labels} value={index} valueLabel={thinkingName} disabled={disabled || !selectedModel} onChange={setPreview} onCommit={(next) => { setPreview(null); if (selectedModel) onChange({ ...value, model: { id: selectedModel.id, thinking: next === 0 ? null : levels[next - 1] } }) }} />
              {!selectedModel && <p className="type-meta text-muted">请先选择模型。</p>}
            </>}
          </div></Popover.Dialog>
        </Popover.Content>
      </Popover></div>
    {status && <p role="status" className="type-meta text-muted">{status}</p>}
    {message && <p role="status" className="type-meta text-muted">{message}</p>}
    {error && <p role="alert">{error}</p>}
  </fieldset>
}
