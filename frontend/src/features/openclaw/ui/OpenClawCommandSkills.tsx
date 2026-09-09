import { useState } from 'react'
import { Button, Input, Label, RefreshButton, TextField } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawSkillSelection } from '../chat/openclawSkillSelection'
import { skillInvocationIssue } from '../chat/openclawSkillInvocation'
import { useComposerSkills } from './useComposerSkills'

export function OpenClawCommandSkills({ chat, active, snapshot, onSelect }: {
  chat: OpenClawChatController
  active: boolean
  snapshot: boolean
  onSelect: (skill: OpenClawSkillSelection) => void
}) {
  const directory = useComposerSkills(chat, active)
  const [search, setSearch] = useState('')
  const [limit, setLimit] = useState(20)
  const scope = chat.workspace.skillScope?.()
  const matches = directory.items.filter((skill) => `${skill.name} ${skill.description ?? ''}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  return <div className="grid min-w-0 gap-3">
    <p className="type-meta text-muted">选择后用于下一条消息</p>
    <TextField value={search} onChange={(value) => { setSearch(value); setLimit(20) }} isDisabled={!active}>
      <Label>筛选 Skills</Label><Input aria-label="筛选 Skills" />
    </TextField>
    {directory.loading && <p className="type-meta text-muted">正在读取 Skills…</p>}
    {directory.error && <div><p className="type-meta text-warning">{directory.error}</p><RefreshButton size="sm" variant="ghost" pending={directory.loading} isDisabled={!active} label="重试 Skills" onPress={directory.retry} /></div>}
    {!directory.loading && !directory.error && !matches.length && <p className="type-body text-muted">没有匹配的 Skills。</p>}
    <ul className="grid min-w-0 gap-3" aria-label="Skills 命令结果">
      {matches.slice(0, limit).map((skill) => {
        const reason = snapshot ? '来源快照禁止调用工具，请先移除快照' : skillInvocationIssue(skill, directory.items)
        return <li key={skill.key} className="flex min-w-0 items-center justify-between gap-2 [overflow-wrap:anywhere]">
          <div className="min-w-0 flex-1"><span className="type-control">{skill.name}</span>
          <p className="type-meta text-muted">{reason ?? skill.description ?? '本次请求使用此 Skill'}</p></div>
          {active && <div><Button size="sm" variant="ghost" isDisabled={Boolean(reason) || !scope} onPress={() => {
            if (scope && !reason) onSelect({ key: skill.key, name: skill.name, gatewayUrl: chat.gatewayUrl, agentId: scope.agentId })
          }}>使用 {skill.name}</Button></div>}
        </li>
      })}
    </ul>
    {matches.length > limit && <Button size="sm" variant="ghost" onPress={() => setLimit((value) => value + 20)}>显示更多 Skills</Button>}
  </div>
}
