import { useEffect, useRef, useState } from 'react'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'

export function useInformationDraft(userId: string, rule: InformationRule) {
  const key = `information-draft:${userId}:${rule.id}`
  const [config, setConfig] = useState<InformationRuleConfig>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || 'null')
      if (saved?.version === rule.version && saved.config?.name && Array.isArray(saved.config.source_ids)) return saved.config
    } catch { /* Storage is optional. */ }
    return rule.config
  })
  const [version, setVersion] = useState(rule.version)
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify({ version, config })) } catch { /* Keep the in-memory draft. */ }
  }, [key, version, config])
  return { config, setConfig, version, active,
    accept: (saved: InformationRule) => { if (active.current) { setVersion(saved.version); setConfig(saved.config) } },
    dirty: JSON.stringify(config) !== JSON.stringify(rule.config) }
}
