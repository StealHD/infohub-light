/* eslint-disable react-hooks/exhaustive-deps, react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback } from 'react'

import { projectChatHistory } from '../chat/openclawHistoryProjection'
import {
  parseOpenClawMediaTicket,
  releaseOpenClawImageUrl,
  ticketUrlForOpenClawMedia,
} from '../openclawMedia'
import type { OpenClawChatMessage, OpenClawClientPort } from '../openclawContracts'
import {
  OPENCLAW_MAX_HISTORY_CHARS,
  OPENCLAW_MAX_MESSAGES,
  boundChatMessages,
  clearOpenClawTranscript,
  mergeOpenClawTranscript,
  readOpenClawTranscript,
  writeOpenClawTranscript,
} from '../storage/openclawTranscriptStore'
import type { OpenClawChatDispatch } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'

type TranscriptUpdate = OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[])

export type OpenClawTranscriptController = {
  persist(update: TranscriptUpdate, keyOverride?: string): OpenClawChatMessage[]
  replace(messages: OpenClawChatMessage[]): void
  restoreLocal(gatewayUrl: string, sessionKey: string): void
  loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
  resolveMedia(client: OpenClawClientPort, sessionKey: string, messages: OpenClawChatMessage[], force?: boolean): Promise<void>
  clear(gatewayUrl: string): void
  reset(): void
}

function releaseRemovedImages(previous: OpenClawChatMessage[], next: OpenClawChatMessage[]): void {
  const retainedUrls = new Set(next.flatMap((message) => (
    message.images?.map((image) => image.url).filter((url): url is string => Boolean(url)) ?? []
  )))
  for (const message of previous) {
    for (const image of message.images ?? []) {
      if (image.url && !retainedUrls.has(image.url)) releaseOpenClawImageUrl(image.url)
    }
  }
}

export function useOpenClawTranscriptController(input: {
  userId: string
  imageIoEnabled: boolean
  mediaOrigins: string[]
  refs: OpenClawLifecycleRefs
  dispatch: OpenClawChatDispatch
  getGatewayUrl: () => string
}): OpenClawTranscriptController {
  const replace = useCallback((messages: OpenClawChatMessage[]) => {
    const next = boundChatMessages(messages)
    releaseRemovedImages(input.refs.transcript.messages, next)
    input.refs.transcript.messages = next
    input.dispatch({ type: 'messages', value: next })
  }, [input.dispatch, input.refs])

  const persist = useCallback((update: TranscriptUpdate, keyOverride?: string): OpenClawChatMessage[] => {
    const current = input.refs.transcript.messages
    const next = boundChatMessages(typeof update === 'function' ? update(current) : update)
    releaseRemovedImages(current, next)
    input.refs.transcript.messages = next
    const key = keyOverride ?? input.refs.session.sessionKey
    if (key && input.refs.transcript.readySessionKey === key) {
      writeOpenClawTranscript(input.userId, input.getGatewayUrl(), key, next)
    }
    input.dispatch({ type: 'messages', value: next })
    return next
  }, [input.dispatch, input.getGatewayUrl, input.refs, input.userId])

  const resolveMedia = useCallback(async (
    client: OpenClawClientPort,
    sessionKey: string,
    sourceMessages: OpenClawChatMessage[],
    force = false,
  ) => {
    if (!input.imageIoEnabled || !input.refs.connection.mediaTicketSupported || input.refs.session.sessionKey !== sessionKey) return
    const candidates = sourceMessages.flatMap((message) => (message.images ?? []).flatMap((image) => (
      image.reference && (force || !image.url) ? [{ image }] : []
    )))
    await Promise.all(candidates.map(async ({ image }) => {
      const reference = image.reference!
      const requestKey = `${sessionKey}:${reference.messageId}:${reference.partIndex}`
      if (input.refs.transcript.mediaTicketRequests.has(requestKey)) return
      input.refs.transcript.mediaTicketRequests.add(requestKey)
      try {
        const ticket = parseOpenClawMediaTicket(await client.request('chat.media.ticket', {
          sessionKey,
          messageId: reference.messageId,
          partIndex: reference.partIndex,
        }))
        const url = ticket ? ticketUrlForOpenClawMedia(input.getGatewayUrl(), ticket, input.mediaOrigins) : null
        if (!url || input.refs.session.sessionKey !== sessionKey) return
        persist((current) => current.map((message) => !message.images?.some((candidate) => candidate.id === image.id)
          ? message
          : {
              ...message,
              images: message.images?.map((candidate) => candidate.id === image.id
                ? {
                    ...candidate,
                    ...(ticket?.mimeType ? { mimeType: ticket.mimeType } : {}),
                    ...(ticket?.width ? { width: ticket.width } : {}),
                    ...(ticket?.height ? { height: ticket.height } : {}),
                    url,
                  }
                : candidate),
            }))
      } catch {
        // A delayed history refresh or an expired media ticket must not fail the conversation.
      } finally {
        input.refs.transcript.mediaTicketRequests.delete(requestKey)
      }
    }))
  }, [input.getGatewayUrl, input.imageIoEnabled, input.mediaOrigins, input.refs, persist])

  const loadHistory = useCallback(async (client: OpenClawClientPort, sessionKey: string, agentId: string) => {
    const history = await client.request('chat.history', {
      sessionKey,
      agentId,
      limit: OPENCLAW_MAX_MESSAGES,
      maxChars: OPENCLAW_MAX_HISTORY_CHARS,
    })
    if (input.refs.session.sessionKey !== sessionKey) return
    const stored = readOpenClawTranscript(input.userId, input.getGatewayUrl(), sessionKey)
    const gatewayMessages = projectChatHistory(history)
    input.refs.transcript.readySessionKey = sessionKey
    persist((current) => mergeOpenClawTranscript(mergeOpenClawTranscript(stored, current), gatewayMessages), sessionKey)
    void resolveMedia(client, sessionKey, gatewayMessages)
  }, [input.getGatewayUrl, input.refs, input.userId, persist, resolveMedia])

  const restoreLocal = useCallback((gatewayUrl: string, sessionKey: string) => {
    input.refs.transcript.readySessionKey = sessionKey
    persist((current) => mergeOpenClawTranscript(
      readOpenClawTranscript(input.userId, gatewayUrl, sessionKey),
      current,
    ), sessionKey)
  }, [input.refs, input.userId, persist])

  const reset = useCallback(() => {
    input.refs.transcript.readySessionKey = null
    input.refs.transcript.mediaTicketRequests.clear()
    replace([])
  }, [input.refs, replace])

  const clear = useCallback((gatewayUrl: string) => {
    clearOpenClawTranscript(input.userId, gatewayUrl)
    reset()
  }, [input.userId, reset])

  return { persist, replace, restoreLocal, loadHistory, resolveMedia, clear, reset }
}
