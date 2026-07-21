import { useEffect, useState } from 'react'

function millisecondsUntilNextLocalDay(now: Date): number {
  const next = new Date(now)
  next.setHours(24, 0, 0, 0)
  return Math.max(1_000, next.getTime() - now.getTime() + 50)
}

export function useLocalDayReference(): Date {
  const [reference, setReference] = useState(() => new Date())

  useEffect(() => {
    let timer = 0
    const refresh = () => {
      const now = new Date()
      setReference(now)
      window.clearTimeout(timer)
      timer = window.setTimeout(refresh, millisecondsUntilNextLocalDay(now))
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    refresh()
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return reference
}
