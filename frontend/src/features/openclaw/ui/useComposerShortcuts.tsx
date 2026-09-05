import { useEffect, useId, useState, type KeyboardEvent, type RefObject } from 'react'
import { ComposerSuggestions, type ComposerSuggestion } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import { skillInvocationIssue } from '../chat/openclawSkillInvocation'
import { composerCommands, findComposerTrigger, replaceComposerTrigger, type ComposerCommand } from './openclawShortcuts'
import type { OpenClawComposerPort } from './openclawComposerPort'
import { useComposerSkills } from './useComposerSkills'

export function useComposerShortcuts(chat: OpenClawChatController, composer: OpenClawComposerPort, inputRef: RefObject<HTMLTextAreaElement | null>) {
  const id = useId()
  const [caret, setCaret] = useState(0)
  const [dismissed, setDismissed] = useState('')
  const [skillsOnly, setSkillsOnly] = useState(false)
  const [active, setActive] = useState('')
  const [issue, setIssue] = useState('')
  const [picker, setPicker] = useState<'model' | 'reasoning' | null>(null)
  const signature = `${caret}:${composer.question}`
  const trigger = dismissed === signature ? null : findComposerTrigger(composer.question, caret)
  const directory = useComposerSkills(chat, Boolean(trigger))
  const scope = chat.workspace.skillScope?.()
  const needle = trigger?.query.toLocaleLowerCase() ?? ''
  const items: ComposerSuggestion[] = []
  if (trigger?.prefix === '/' && !skillsOnly) for (const command of composerCommands) {
    if (!`${command.title} ${command.description}`.toLocaleLowerCase().includes(needle)) continue
    const unavailable = ['new', 'model', 'reasoning', 'worktree'].includes(command.id) && (chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading || chat.status !== 'connected')
      || command.id === 'model' && !chat.models.length
      || command.id === 'reasoning' && (!chat.thinkingOptions.length || chat.models.find((model) => model.id === chat.runtimeSelection.modelId)?.reasoning === false)
    items.push({ ...command, icon: ({ skills: 'Sparkles', new: 'Plus', model: 'Bot', reasoning: 'Brain', worktree: 'GitCompareArrows', status: 'Activity', help: 'BookOpen' } as const)[command.id], id: `command:${command.id}`, group: '快捷操作', disabled: unavailable })
  }
  for (const skill of directory.items) {
    if (!`${skill.name} ${skill.description ?? ''}`.toLocaleLowerCase().includes(needle)) continue
    const reason = composer.snapshot ? '来源快照禁止调用工具，请先移除快照' : skillInvocationIssue(skill, directory.items)
    items.push({ id: `skill:${skill.key}`, group: 'Skills', title: skill.name, description: reason ?? skill.description ?? '本次请求使用此 Skill', disabled: Boolean(reason) || !composer.selectSkill || !scope })
  }
  if (trigger?.prefix === '@' && !skillsOnly) for (const material of composer.materials ?? []) {
    if (material.title.toLocaleLowerCase().includes(needle)) items.push({ id: `material:${material.id}`, group: '已附带材料', icon: 'Paperclip', title: material.title, description: '引用标题，不重复添加附件' })
  }
  const enabled = items.filter((item) => !item.disabled)
  const activeId = enabled.find((item) => item.id === active)?.id ?? enabled[0]?.id
  const activeIndex = items.findIndex((item) => item.id === activeId)
  const open = Boolean(trigger)
  useEffect(() => {
    if (open && activeIndex >= 0) document.getElementById(`${id}-${activeIndex}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [id, activeIndex, activeId, open])

  function restore(position: number) {
    requestAnimationFrame(() => { inputRef.current?.focus(); inputRef.current?.setSelectionRange(position, position); setCaret(position) })
  }
  function close() { setDismissed(signature); setSkillsOnly(false) }
  function choose(selectedId: string) {
    if (!trigger || !items.some((item) => item.id === selectedId && !item.disabled)) return
    const skill = directory.items.find((item) => `skill:${item.key}` === selectedId)
    const material = composer.materials?.find((item) => `material:${item.id}` === selectedId)
    const command = selectedId.startsWith('command:') ? selectedId.slice(8) as ComposerCommand : null
    if (command === 'skills') {
      const next = replaceComposerTrigger(composer.question, trigger, '/')
      if (next) { composer.setQuestion(next.text); setSkillsOnly(true); restore(next.caret) }
      return
    }
    const next = replaceComposerTrigger(composer.question, trigger, material ? `「${material.title}」` : '')
    if (!next) { setIssue('引用后超过 1200 字限制，请先缩短问题。'); return }
    setIssue(''); close()
    if (skill && scope) composer.selectSkill?.({ key: skill.key, name: skill.name, gatewayUrl: chat.gatewayUrl, agentId: scope.agentId }, next.text)
    else composer.setQuestion(next.text)
    restore(next.caret)
    if (command === 'model' || command === 'reasoning') setPicker(command)
    else if (command) composer.command?.(command, next.text)
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!trigger) return false
    if (event.key === 'Tab') { close(); return false }
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return true }
    if (event.shiftKey) return false
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const index = enabled.findIndex((item) => item.id === activeId)
      setActive(enabled[(index + (event.key === 'ArrowDown' ? 1 : -1) + enabled.length) % enabled.length]?.id ?? '')
      return true
    }
    if (event.key === 'Enter') { event.preventDefault(); if (activeId) choose(activeId); else close(); return true }
    return false
  }
  return {
    setCaret, inputChanged: (position: number) => { setCaret(position); setDismissed(''); setActive('') }, keyDown, issue, picker, closePicker: () => setPicker(null),
    aria: { 'aria-autocomplete': 'list' as const, 'aria-controls': trigger ? id : undefined, 'aria-activedescendant': trigger && activeIndex >= 0 ? `${id}-${activeIndex}` : undefined },
    suggestions: trigger ? <ComposerSuggestions anchor={inputRef} id={id} items={items} activeId={activeId} loading={directory.loading} error={directory.error} onChoose={choose} onHighlight={setActive} onClose={close} onRetry={directory.retry} /> : null,
  }
}
