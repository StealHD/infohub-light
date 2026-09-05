import { useCallback, useEffect, useState } from 'react'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawSkill, OpenClawWorkspaceController } from '../workspace/openclawWorkspaceContracts'

const requests = new WeakMap<OpenClawWorkspaceController, { key: string; result: Promise<OpenClawSkill[]> }>()
export function useComposerSkills(chat: OpenClawChatController, open: boolean) {
  const scope = chat.workspace.skillScope?.()
  const hasScope = Boolean(scope)
  const key = JSON.stringify([chat.gatewayUrl, chat.sessionKey, scope?.agentId, scope?.generation, chat.status])
  const [state, setState] = useState({ key: '', items: [] as OpenClawSkill[], loading: false, error: '' })
  const [revision, setRevision] = useState(0)
  const retry = useCallback(async () => { requests.delete(chat.workspace); setRevision((value) => value + 1) }, [chat.workspace])
  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'skills.changed') { requests.delete(chat.workspace); setRevision((value) => value + 1) }
  }), [chat.workspace])
  useEffect(() => {
    if (!open) return
    let active = true
    const load = async () => {
      if (!hasScope || chat.status !== 'connected' || !chat.workspace.capabilities()['skills.status']) {
        if (active) setState({ key, items: [], loading: false, error: '当前连接未提供 Skill 快捷调用。已有材料仍可引用。' })
        return
      }
      setState((current) => ({ key, items: current.key === key ? current.items : [], loading: true, error: '' }))
      let cached = requests.get(chat.workspace)
      if (!cached || cached.key !== key) {
        cached = { key, result: chat.workspace.skillsStatus().then((status) => status.skills) }
        requests.set(chat.workspace, cached)
      }
      try {
        const items = await cached.result
        if (active) setState({ key, items, loading: false, error: '' })
      } catch {
        if (requests.get(chat.workspace) === cached) requests.delete(chat.workspace)
        if (active) setState((current) => ({ ...current, key, loading: false, error: 'Skills 读取失败，请重试。' }))
      }
    }
    void Promise.resolve().then(() => { if (active) void load() })
    return () => { active = false }
  }, [chat.workspace, chat.status, key, open, revision, hasScope])
  return { items: state.key === key ? state.items : [], loading: state.key === key ? state.loading : open, error: state.key === key ? state.error : '', retry }
}
