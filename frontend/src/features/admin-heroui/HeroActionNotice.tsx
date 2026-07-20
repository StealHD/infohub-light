import { useEffect, useRef } from 'react'

import type { ActionPhase } from '../../app/ActionFeedback'
import { Button, Icons } from '../../design-system'
import { HeroNotice } from './HeroAdminControls'

type TerminalActionPhase = Exclude<ActionPhase, 'pending' | 'queued' | 'running'>

export function HeroActionNotice({ phase, message, onClose }: { phase: TerminalActionPhase; message: string; onClose: () => void }) {
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const timer = window.setTimeout(() => onCloseRef.current(), phase === 'succeeded' ? 4_000 : 8_000)
    return () => window.clearTimeout(timer)
  }, [message, phase])

  const warning = phase === 'partial' || phase === 'blocked'
  return <HeroNotice title={message} status={phase === 'succeeded' ? 'success' : warning ? 'warning' : 'danger'} role={phase === 'failed' || phase === 'blocked' ? 'alert' : 'status'}>
    <Button size="sm" variant="ghost" isIconOnly aria-label="关闭通知" onPress={onClose}><Icons.X size={15} /></Button>
  </HeroNotice>
}
