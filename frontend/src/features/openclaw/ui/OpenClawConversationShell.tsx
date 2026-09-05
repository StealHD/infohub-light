import type { OpenClawChatController } from '../openclawContracts'
import { OpenClawComposer } from './OpenClawComposer'
import { OpenClawSetupPanel } from './OpenClawSetupPanel'
import { OpenClawTimeline } from './OpenClawTimeline'
import type { OpenClawComposerPort } from './openclawComposerPort'

export function OpenClawConversationShell({ chat, composer, variant = 'compact' }: {
  chat: OpenClawChatController
  composer: OpenClawComposerPort
  variant?: 'compact' | 'workspace'
}) {
  if (chat.status !== 'connected' && chat.status !== 'reconnecting') {
    return <OpenClawSetupPanel key={chat.gatewayUrl} chat={chat} variant={variant} />
  }
  return <>
    <OpenClawTimeline chat={chat} composer={composer} variant={variant} />
    <OpenClawComposer chat={chat} composer={composer} variant={variant} />
  </>
}
