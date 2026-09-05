import type { ReactNode } from 'react'

import type { OpenClawImageAttachment } from '../openclawMedia'
import type { OpenClawSkillSelection } from '../chat/openclawSkillSelection'
import type { ComposerCommand } from './openclawShortcuts'

export type OpenClawComposerPort = {
  selectedSkill?: OpenClawSkillSelection
  materials?: { id: string; title: string }[]
  selectSkill?: (skill: OpenClawSkillSelection | undefined, question: string) => void
  command?: (command: ComposerCommand, question: string) => boolean
  commandEntries?: { id: string; afterMessageId?: string; content: ReactNode }[]
  question: string
  itemCount: number
  snapshot: { sourceName: string; itemCount: number } | null
  contextSummary: ReactNode
  setQuestion(question: string): void
  send(attachments: OpenClawImageAttachment[]): Promise<boolean>
  editFailed(messageId: string): void
}
