import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { FormSelect, RefreshButton } from '../../design-system'
import { useModelRefresh } from './useModelRefresh'

export function InformationModelFields({ value, onChange, disabled, compactHeading = false }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void; disabled: boolean; compactHeading?: boolean
}) {
  const { models, refresh, refreshing, message, error } = useModelRefresh()
  const selectedModel = models.data?.models.find((model) => model.id === value.model?.id)
  const status = models.isPending ? '正在加载模型目录…'
    : models.isError ? '模型目录加载失败，请刷新重试。'
    : models.data?.status === 'unavailable' ? '尚未读取模型目录；请刷新重试。'
    : models.data?.status === 'stale' ? '模型目录已过期，请刷新。'
    : !models.data?.models.length ? '当前没有可用模型，请检查模型配置后刷新。'
    : value.model && !selectedModel ? '所选模型已不可用，请重新选择。'
    : ''
  return <fieldset className="grid gap-3">{!compactHeading && <legend className="type-section-title">模型</legend>}
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="type-control">分析模型</p>
        <RefreshButton pending={refreshing || models.isFetching} aria-label="刷新模型目录" onPress={refresh} /></div>
      <FormSelect label="选择模型" value={value.model?.id || ''} isDisabled={disabled || models.data?.status !== 'ready' || !models.data.models.length}
        options={(models.data?.models || []).map((model) => ({ id: model.id, label: model.name }))}
        onChange={(id) => onChange({ ...value, model: { id, thinking: null } })} />
      {selectedModel && selectedModel.thinking_levels.length > 0 && <FormSelect label="推理强度" value={value.model?.thinking || 'default'} isDisabled={disabled}
        options={[{ id: 'default', label: '模型默认' }, ...selectedModel.thinking_levels.map((id) => ({ id, label: id }))]}
        onChange={(thinking) => onChange({ ...value, model: { id: selectedModel.id, thinking: thinking === 'default' ? null : thinking } })} />}
      {status && <p role="status" className="type-meta text-muted">{status}</p>}
      {message && <p role="status" className="type-meta text-muted">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </fieldset>
}
