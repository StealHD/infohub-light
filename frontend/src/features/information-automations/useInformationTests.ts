import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { InformationTest } from '../../api/informationAutomationService'
import { useInformationContext } from './useInformationContext'

export type TestArticleSelection = { id: string; title: string }
export type InformationTestSession = {
  ruleId: string; version: number; selection: TestArticleSelection[]
  phase: 'idle' | 'submitting' | 'pending' | 'judging' | 'quota_wait' | 'completed' | 'failed' | 'submission_unknown'
  data?: InformationTest; error?: string; requestId?: string
}

const keyFor = (userId: string, ruleId: string, version: number) => `${userId}:${ruleId}:${version}`
const phaseFor = (data: InformationTest): InformationTestSession['phase'] => data.status || 'completed'
export const informationTestStatusLabel = (phase: InformationTestSession['phase']) => ({
  idle: '准备测试', submitting: '正在提交测试', pending: '测试排队中', judging: '测试分析中', quota_wait: '测试等待额度',
  completed: '测试已完成', failed: '测试失败', submission_unknown: '测试提交结果未知',
})[phase]

export function useInformationTests() {
  const { api, userId } = useInformationContext()
  const [sessions, setSessions] = useState<Record<string, InformationTestSession>>({})
  const sessionsRef = useRef(sessions)
  const polling = useRef(new Set<string>())
  const starting = useRef(new Set<string>())
  useEffect(() => { sessionsRef.current = sessions }, [sessions])

  useEffect(() => {
    let active = true
    const poll = async () => {
      for (const [key, session] of Object.entries(sessionsRef.current)) {
        if (!key.startsWith(`${userId}:`) || session.data?.requires_review || !session.data?.preview_id || !['pending', 'judging', 'quota_wait'].includes(session.phase) || polling.current.has(key)) continue
        polling.current.add(key)
        try {
          const data = await api.informationTestPreview(session.ruleId, session.data.preview_id)
          if (active) setSessions((current) => current[key]?.data?.preview_id === session.data?.preview_id ? { ...current, [key]: { ...current[key], phase: phaseFor(data), data, error: undefined } } : current)
        } catch {
          if (active) setSessions((current) => current[key]?.data?.preview_id === session.data?.preview_id ? { ...current, [key]: { ...current[key], error: '测试进度读取失败，可稍后重新打开查看。' } } : current)
        } finally { polling.current.delete(key) }
      }
    }
    const timer = window.setInterval(() => void poll(), 1500)
    void poll()
    return () => { active = false; window.clearInterval(timer) }
  }, [api, userId])

  const session = (ruleId: string, version: number): InformationTestSession => sessions[keyFor(userId, ruleId, version)] || {
    ruleId, version, selection: [], phase: 'idle',
  }
  const restore = useCallback(async (ruleId: string, version: number) => {
    const key = keyFor(userId, ruleId, version)
    const requestId = sessionsRef.current[key]?.requestId
    try {
      const data = await api.informationTestPreview(ruleId, 'latest')
      if (data?.version === version) setSessions((all) => all[key]?.phase === 'submitting' || all[key]?.requestId !== requestId ? all : {
        ...all, [key]: { ...all[key], ruleId, version, selection: all[key]?.selection.length ? all[key].selection : data.selection || [], phase: phaseFor(data), data },
      })
    } catch { /* Preserve the current draft and submission diagnostics. */ }
  }, [api, userId])
  const select = (ruleId: string, version: number, selection: TestArticleSelection[]) => setSessions((current) => {
    const key = keyFor(userId, ruleId, version); return { ...current, [key]: { ...(current[key] || { ruleId, version, phase: 'idle' }), selection } }
  })
  const start = async (ruleId: string, version: number) => {
    const key = keyFor(userId, ruleId, version)
    const current = sessionsRef.current[key]
    if (!current?.selection.length || starting.current.has(key) || (['submitting', 'pending', 'judging', 'quota_wait'].includes(current.phase) && !current.data?.requires_review)) return
    starting.current.add(key)
    const startedAt = performance.now()
    const snapshot = [...current.selection]
    const requestId = current.phase === "submission_unknown" && current.requestId ? current.requestId : crypto.randomUUID()
    setSessions((all) => ({ ...all, [key]: { ...current, selection: snapshot, requestId, phase: 'submitting', data: undefined, error: undefined } }))
    try {
      const data = await api.testInformationRule(ruleId, version, snapshot.map((item) => item.id), requestId)
      setSessions((all) => ({ ...all, [key]: { ...all[key], selection: snapshot, phase: phaseFor(data), data, error: undefined } }))
    } catch (cause) {
      const rejected = cause instanceof ApiError && cause.code !== 'invalid_response' && cause.code !== 'request_failed'
      setSessions((all) => ({ ...all, [key]: { ...all[key], selection: snapshot, phase: rejected ? 'failed' : 'submission_unknown', error: rejected ? cause.message : '无法确认测试是否已提交。可核对最近记录，或使用同一请求编号手动重试。' } }))
    } finally {
      // A fast response must not turn the second click of one gesture into a new test.
      await new Promise((resolve) => window.setTimeout(resolve, Math.max(0, 500 - (performance.now() - startedAt))))
      starting.current.delete(key)
    }
  }
  return { sessions, session, select, start, restore }
}
