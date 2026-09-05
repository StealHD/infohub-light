import type { OpenClawChatController } from './openclawContracts'

export function logoutOpenClawWorkspace(chat: Pick<OpenClawChatController, 'clearTranscript' | 'disconnect'>, logout: () => void) {
  chat.clearTranscript()
  chat.disconnect()
  logout()
}
