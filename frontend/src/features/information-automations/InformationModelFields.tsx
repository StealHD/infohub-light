import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { FormSelect, RefreshButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'

export function InformationModelFields({ value, onChange, disabled }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void; disabled: boolean
}) {
  const { api, userId } = useInformationContext()
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const models = useQuery({ queryKey: ['information-models', userId], queryFn: ({ signal }) => api.informationModels(signal), refetchInterval: 15000 })
  const selectedModel = models.data?.models.find((model) => model.id === value.model?.id)
  return <fieldset className="grid gap-3"><legend className="type-section-title">模型</legend>
      <div className="flex flex-wrap items-center gap-2"><p className="type-meta text-muted">自动读取 OpenClaw 允许用于独立分析的模型。</p>
        <RefreshButton pending={refreshing || models.isFetching} aria-label="刷新模型目录" onPress={async () => {
          setRefreshing(true); setError('')
          try { await api.refreshInformationModels(); await models.refetch() }
          catch { setError('模型目录刷新失败，请重试。') } finally { setRefreshing(false) }
        }} /></div>
      <FormSelect label="分析模型" value={value.model?.id || ''} isDisabled={disabled || models.data?.status !== 'ready' || !models.data.models.length}
        options={(models.data?.models || []).map((model) => ({ id: model.id, label: model.name }))}
        onChange={(id) => onChange({ ...value, model: { id, thinking: null } })} />
      {selectedModel && selectedModel.thinking_levels.length > 0 && <FormSelect label="推理强度" value={value.model?.thinking || 'default'} isDisabled={disabled}
        options={[{ id: 'default', label: '模型默认' }, ...selectedModel.thinking_levels.map((id) => ({ id, label: id }))]}
        onChange={(thinking) => onChange({ ...value, model: { id: selectedModel.id, thinking: thinking === 'default' ? null : thinking } })} />}
      <p role="status" className="type-meta text-muted">{models.isPending ? '正在加载模型目录…'
        : models.isError ? '模型目录加载失败，请刷新重试。'
        : models.data?.status === 'unavailable' ? '尚未收到独立分析 connector 的模型目录。请先启动 connector，接入后本页会自动更新。'
        : models.data?.status === 'stale' ? '模型目录已过期，请检查独立分析 connector 是否在线，恢复后本页会自动更新。'
        : !models.data?.models.length ? 'OpenClaw 暂无获准用于独立分析的模型，请检查模型配置与授权后刷新。'
        : value.model && !selectedModel ? '所选模型已不可用，请重新选择。'
        : `已加载 ${models.data.models.length} 个模型，请选择分析模型。`}</p>
      {error && <p role="alert">{error}</p>}
    </fieldset>
}
