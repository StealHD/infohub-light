import type { OpenClawChatController } from '../openclawContracts'
import { OpenClawComposer } from './OpenClawComposer'
import { OpenClawSetupPanel } from './OpenClawSetupPanel'
import { OpenClawTimeline } from './OpenClawTimeline'
import type { OpenClawComposerPort } from './openclawComposerPort'

export function OpenClawConversationShell({ chat, composer }: {
  chat: OpenClawChatController
  composer: OpenClawComposerPort
}) {
  if (chat.status !== 'connected' && chat.status !== 'reconnecting') {
    return <OpenClawSetupPanel key={chat.gatewayUrl} chat={chat} />
  }
  return <>
    <OpenClawTimeline chat={chat} composer={composer} />
    <OpenClawComposer chat={chat} composer={composer} />
  </>
}
