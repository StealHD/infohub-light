import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { CatalogSource, SourceTypeDefinition, Subscription } from '../../api/types'
import { sourceTypeLabel } from '../subscriptions/subscriptionModel'

export type SourceCreationRecovery = {
  title: string
  description: string
}

class SourceSubscriptionPendingError extends Error {
  readonly recovery: SourceCreationRecovery

  constructor(recovery: SourceCreationRecovery) {
    super(recovery.title)
    this.name = 'SourceSubscriptionPendingError'
    this.recovery = recovery
  }
}

export function unavailableSourceCopy(definition: SourceTypeDefinition) {
  if (definition.unavailable_reason === 'workspace_credential_unavailable') return {
    title: `${definition.label || sourceTypeLabel(definition.type)}暂不可用`,
    description: '工作区的平台连接当前不可用。现有来源和历史内容不会受到影响。',
    settingsLabel: '打开工作区密钥设置',
    settingsHref: '/settings/secrets',
  }
  return {
    title: `${definition.label || sourceTypeLabel(definition.type)}正在准备中`,
    description: '管理员完成平台配置后即可新增；现有来源和历史内容不会受到影响。',
    settingsLabel: '打开平台设置',
    settingsHref: '/settings/actorops',
  }
}

export function sourceCreationRecovery(caught: unknown): SourceCreationRecovery | null {
  if (caught instanceof SourceSubscriptionPendingError) return caught.recovery
  if (!(caught instanceof ApiError)) return null
  if (caught.code === 'source_key_conflict') {
    return {
      title: '已有相同来源',
      description: '请到来源库订阅当前账户可见的现有来源；如果它已在“我的订阅”中，无需重复操作。也可以修改来源目标后重试。',
    }
  }
  if (caught.code === 'source_identity_migration_required') {
    return {
      title: '来源身份升级尚未完成',
      description: '请联系管理员完成来源身份迁移后重试。当前表单内容已保留。',
    }
  }
  return null
}

export async function createAndSubscribeSource(
  api: Pick<ServiceApi, 'createSource' | 'subscribe'>,
  payload: Record<string, unknown>,
  pending: { current: CatalogSource | null },
  subscriptions: Subscription[],
  onPendingChange?: (pending: boolean) => void,
) {
  const source = pending.current ?? await api.createSource(payload)
  pending.current = source
  onPendingChange?.(true)
  if (source.subscribed || source.subscription_id || subscriptions.some((item) => item.source_id === source.id)) {
    pending.current = null
    onPendingChange?.(false)
    return { alreadySubscribed: true as const, sourceActivation: null, reused: 0 }
  }
  if (!(source.can_subscribe ?? source.enabled)) {
    pending.current = null
    onPendingChange?.(false)
    throw new SourceSubscriptionPendingError({
      title: '已有来源当前已停用',
      description: '现有来源设置和停用状态保持不变。请到来源库查看，或由有权限的管理员明确启用。',
    })
  }
  let result: Awaited<ReturnType<ServiceApi['subscribe']>>
  try {
    result = await api.subscribe(source.id)
  } catch (caught) {
    const specific = sourceCreationRecovery(caught)
    throw new SourceSubscriptionPendingError({
      title: specific?.title ?? '来源已创建，订阅尚未完成',
      description: `来源设置已保留，重试只会恢复订阅，不会再次创建或覆盖配置。${specific ? ` ${specific.description}` : ' 请检查网络后重试。'}`,
    })
  }
  pending.current = null
  onPendingChange?.(false)
  return {
    alreadySubscribed: false as const,
    sourceActivation: result.source_activation,
    reused: result.subscription.reused_item_count ?? 0,
  }
}
