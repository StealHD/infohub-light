import type { ReactNode } from 'react'

import type { OpenClawImageAttachment } from '../openclawMedia'

export type OpenClawComposerPort = {
  question: string
  itemCount: number
  snapshot: { sourceName: string; itemCount: number } | null
  contextSummary: ReactNode
  setQuestion(question: string): void
  send(attachments: OpenClawImageAttachment[]): Promise<boolean>
  editFailed(messageId: string): void
}
