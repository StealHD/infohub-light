import { useCallback, useEffect, useRef, useState } from 'react'
import { OpenClawAdminSessionController, type OpenClawAdminSessionState } from '../openclaw/admin/OpenClawAdminSessionController'
import { OpenClawWorkspaceError } from '../openclaw'

export function useOpenClawAdminSession(gatewayUrl: string) {
  const [admin, setAdmin] = useState<OpenClawAdminSessionController | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [state, setState] = useState<OpenClawAdminSessionState>('disconnected')
  const [error, setError] = useState('')
  const generation = useRef(0)
  const mounted = useRef(true)
  const adminRef = useRef<OpenClawAdminSessionController | null>(null)

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  const close = useCallback(() => {
    generation.current += 1
    adminRef.current?.close()
    adminRef.current = null
    setAdmin(null)
    setConnecting(false)
    setState('disconnected')
  }, [])

  useEffect(() => close, [close, gatewayUrl])

  const connect = useCallback(async (token: string) => {
    const operation = ++generation.current
    setConnecting(true)
    setState('connecting')
    setError('')
    try {
      const next = await OpenClawAdminSessionController.connect({ gatewayUrl, token })
      if (!mounted.current || operation !== generation.current) {
        next.close()
        return false
      }
      next.subscribe((nextState) => {
        if (!mounted.current || operation !== generation.current) return
        setState(nextState)
        if (nextState !== 'authorized' && nextState !== 'connecting') { adminRef.current = null; setAdmin(null) }
      })
      adminRef.current?.close()
      adminRef.current = next
      setAdmin(next)
      return true
    } catch (reason) {
      if (mounted.current && operation === generation.current) {
        setError(reason instanceof OpenClawWorkspaceError ? reason.message : '临时管理连接失败，请检查权限与 Gateway 状态。')
        setState('failed')
      }
      return false
    } finally {
      if (mounted.current && operation === generation.current) setConnecting(false)
    }
  }, [gatewayUrl])

  return { admin, connecting, state, error, connect, close }
}
