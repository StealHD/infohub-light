import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { createAndSubscribeSource, sourceCreationRecovery } from './sourceCreationRecovery'

describe('sourceCreationRecovery', () => {
  it('uses safe local copy for a source identity conflict', () => {
    const recovery = sourceCreationRecovery(new ApiError(409, {
      code: 'source_key_conflict',
      message: 'private source belongs to user-secret@example.test',
      action: 'Use internal source id hidden-source-1',
    }))

    expect(recovery).toEqual({
      title: '已有相同来源',
      description: '请到来源库订阅当前账户可见的现有来源；如果它已在“我的订阅”中，无需重复操作。也可以修改来源目标后重试。',
    })
    expect(JSON.stringify(recovery)).not.toContain('user-secret')
    expect(JSON.stringify(recovery)).not.toContain('hidden-source-1')
  })

  it('explains the migration dependency without exposing server details', () => {
    const recovery = sourceCreationRecovery(new ApiError(409, {
      code: 'source_identity_migration_required',
      message: 'database /private/path schema=45',
    }))

    expect(recovery).toEqual({
      title: '来源身份升级尚未完成',
      description: '请联系管理员完成来源身份迁移后重试。当前表单内容已保留。',
    })
    expect(JSON.stringify(recovery)).not.toContain('/private/path')
  })

  it('leaves unrelated failures to the existing form feedback', () => {
    expect(sourceCreationRecovery(new Error('network down'))).toBeNull()
    expect(sourceCreationRecovery(new ApiError(400, {
      code: 'invalid_source_config',
      message: 'invalid',
    }))).toBeNull()
  })

  it('retries only subscription after a source was created', async () => {
    const source = { id: 'created-source', type: 'rss', display_name: '研究源', scope: 'private' as const, enabled: true }
    const subscription = { id: 'subscription-1', user_id: 'user-1', source_id: source.id, enabled: true }
    const calls: string[] = []
    const api = {
      createSource: vi.fn(async () => { calls.push('create'); return source }),
      subscribe: vi.fn()
        .mockImplementationOnce(async () => { calls.push('subscribe-1'); throw new Error('network lost') })
        .mockImplementationOnce(async () => { calls.push('subscribe-2'); return { subscription } }),
    }
    const pending = { current: null }

    await expect(createAndSubscribeSource(api as never, { display_name: '研究源' }, pending, [])).rejects.toThrow('来源已创建，订阅尚未完成')
    expect(pending.current).toEqual(source)
    await expect(createAndSubscribeSource(api as never, { display_name: '被保留的表单' }, pending, [])).resolves.toMatchObject({ alreadySubscribed: false })

    expect(calls).toEqual(['create', 'subscribe-1', 'subscribe-2'])
    expect(api.createSource).toHaveBeenCalledOnce()
    expect(pending.current).toBeNull()
  })

  it('wraps subscription failure in safe partial-completion guidance', async () => {
    const source = { id: 'created-source', type: 'rss', display_name: '研究源', scope: 'private' as const, enabled: true }
    const api = {
      createSource: vi.fn().mockResolvedValue(source),
      subscribe: vi.fn().mockRejectedValue(new ApiError(409, {
        code: 'source_identity_migration_required', message: 'database /secret/path',
      })),
    }
    const pending = { current: null }

    const error = await createAndSubscribeSource(api as never, {}, pending, []).catch((caught) => caught)
    expect(sourceCreationRecovery(error)).toEqual({
      title: '来源身份升级尚未完成',
      description: '来源设置已保留，重试只会恢复订阅，不会再次创建或覆盖配置。 请联系管理员完成来源身份迁移后重试。当前表单内容已保留。',
    })
    expect(JSON.stringify(sourceCreationRecovery(error))).not.toContain('/secret/path')
  })

  it('does not submit a duplicate subscription when current state already contains it', async () => {
    const source = { id: 'existing-source', type: 'rss', display_name: '已有来源', scope: 'private' as const, enabled: false }
    const api = { createSource: vi.fn().mockResolvedValue(source), subscribe: vi.fn() }
    const pending = { current: null }

    const outcome = await createAndSubscribeSource(api as never, {}, pending, [{
      id: 'existing-subscription', user_id: 'user-1', source_id: source.id, enabled: false,
    }])

    expect(outcome.alreadySubscribed).toBe(true)
    expect(api.subscribe).not.toHaveBeenCalled()
    expect(source.enabled).toBe(false)
  })

  it('keeps an unsubscribed existing source disabled and unchanged', async () => {
    const source = { id: 'disabled-source', type: 'rss', display_name: '停用来源', scope: 'private' as const, enabled: false, can_subscribe: false, config: { url: 'https://example.test/feed' } }
    const api = { createSource: vi.fn().mockResolvedValue(source), subscribe: vi.fn() }
    const pending = { current: null }

    const error = await createAndSubscribeSource(api as never, { enabled: true, config: { url: 'changed' } }, pending, []).catch((caught) => caught)

    expect(sourceCreationRecovery(error)).toEqual({
      title: '已有来源当前已停用',
      description: '现有来源设置和停用状态保持不变。请到来源库查看，或由有权限的管理员明确启用。',
    })
    expect(api.subscribe).not.toHaveBeenCalled()
    expect(source).toMatchObject({ enabled: false, config: { url: 'https://example.test/feed' } })
  })

  it('subscribes a newly created managed source that is pending preparation', async () => {
    const source = { id: 'managed-pending', type: 'apify_social', setup_type: 'x_profile', display_name: 'X 来源', scope: 'private' as const, enabled: false, can_subscribe: true }
    const subscription = { id: 'managed-sub', user_id: 'user-1', source_id: source.id, enabled: true }
    const api = { createSource: vi.fn().mockResolvedValue(source), subscribe: vi.fn().mockResolvedValue({ subscription }) }
    const pendingStates: boolean[] = []

    const outcome = await createAndSubscribeSource(api as never, {}, { current: null }, [], (value) => pendingStates.push(value))

    expect(outcome.alreadySubscribed).toBe(false)
    expect(api.subscribe).toHaveBeenCalledWith(source.id)
    expect(pendingStates).toEqual([true, false])
    expect(source.enabled).toBe(false)
  })
})
