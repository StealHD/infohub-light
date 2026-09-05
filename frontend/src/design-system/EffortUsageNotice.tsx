import { useEffect, useState } from 'react'

/** A short, non-blocking usage reminder; runtime state never waits for motion. */
export function EffortUsageNotice({ enabled, message }: { enabled: boolean; message: string }) {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(false), 1400)
    return () => window.clearTimeout(timer)
  }, [])
  return enabled && visible ? <span className="effort-usage-notice type-control" role="status">{message}</span> : null
}
