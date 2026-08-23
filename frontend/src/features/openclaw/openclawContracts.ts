import type { OpenClawCredentialVault } from './openclawCredentialVault'
import type {
  GatewayHello,
  OpenClawGatewayClientOptions,
} from './openclawGateway'
import type {
  OpenClawImageAttachment,
  OpenClawMessageImage,
} from './openclawMedia'

export type OpenClawConnectionStatus = 'disabled' | 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
export type OpenClawToolsStatus = 'unknown' | 'available' | 'missing'
export type OpenClawRunPhase =
  | 'sending'
  | 'waiting'
  | 'thinking'
  | 'using_tool'
  | 'composing'
  | 'streaming'
  | 'stopping'
  | 'completed'
  | 'aborted'
  | 'failed'

export type OpenClawRunActivity = {
  id: string
  label: string
  status: 'running' | 'completed' | 'failed' | 'stopped'
  startedAt: number
  endedAt?: number
}

export type OpenClawRunTrace = {
  runId: string | null
  phase: OpenClawRunPhase
  status: 'running' | 'completed' | 'aborted' | 'failed'
  startedAt: number
  endedAt?: number
  activities: OpenClawRunActivity[]
}

export type OpenClawContextItem = {
  articleId: string
  title: string
  sourceName?: string
  sourceUrl?: string
  sourceAvatarUrl?: string
  publishedAt?: string
  resourceType?: 'feed_item' | 'job'
  jobId?: string
  statusLabel?: string
  detail?: string
}

export type OpenClawSourceSnapshotItem = {
  articleId: string
  title: string
  summary?: string
  publishedAt?: string
}

export type OpenClawSourceSnapshot = {
  sourceName: string
  windowLabel: string
  itemCount: number
  items: OpenClawSourceSnapshotItem[]
}

export type OpenClawSourceReference = {
  title: string
  url: string
  sourceName?: string
  sourceAvatarUrl?: string
}

export type OpenClawChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  status?: 'pending' | 'sent' | 'failed' | 'aborted'
  contextCount?: number
  contextSources?: OpenClawSourceReference[]
  sendSnapshot?: OpenClawSendSnapshot
  createdAt?: number
  origin?: 'local' | 'gateway'
  mergeId?: string
  clientTurnId?: string
  images?: OpenClawMessageImage[]
}

export type OpenClawSendRequest = {
  displayText: string
  gatewayPrompt: string
  contextItems: OpenClawContextItem[]
  contextCount?: number
  sourceSnapshot?: OpenClawSourceSnapshot
  attachments?: OpenClawImageAttachment[]
}

export type OpenClawSendSnapshot = OpenClawSendRequest & {
  idempotencyKey: string
  modelId: string | null
  thinkingLevel: string | null
}

export type OpenClawThinkingOption = { id: string; label: string }

export type OpenClawModelOption = {
  id: string
  name: string
  provider: string
  alias?: string
  contextWindow?: number
  reasoning?: boolean
  thinkingLevels?: OpenClawThinkingOption[]
  thinkingDefault?: string
  supportsImages: boolean
}

export type OpenClawRuntimeSelection = {
  modelId: string | null
  thinkingLevel: string | null
  defaultModelId: string | null
  defaultThinkingLevel: string | null
}

export type OpenClawContextUsage = {
  sessionKey: string
  usedTokens: number
  contextTokens: number
  percent: number
  modelId?: string
}

export type OpenClawModelSwitchFallback = { modelId: string; modelName: string }

export type OpenClawSetupIssue = {
  kind: 'origin' | 'pairing' | 'auth' | 'protocol' | 'permission' | 'network' | 'session' | 'unknown'
  message: string
  requestId?: string
}

export type OpenClawSanitizedAgentEvent = {
  runId: string
  seq: number
  stream: string
  phase: string | null
  timestamp: number
  toolCallId: string | null
  toolKey: string | null
  toolLabel: string | null
  failed: boolean
}

export interface OpenClawClientPort {
  connect(): Promise<GatewayHello>
  request<T>(method: string, params: Record<string, unknown>): Promise<T>
  close(): void
}

export interface OpenClawTranscriptPort {
  read(userId: string, gatewayUrl: string, sessionKey: string): OpenClawChatMessage[]
  write(userId: string, gatewayUrl: string, sessionKey: string, messages: OpenClawChatMessage[]): void
  clear(userId: string, gatewayUrl: string, sessionKey?: string | null): void
}

export type OpenClawDomainEvent =
  | { type: 'connection'; status: OpenClawConnectionStatus }
  | { type: 'session'; sessionKey: string | null }
  | { type: 'run'; trace: OpenClawRunTrace | null }
  | { type: 'gateway'; name: string; payload: unknown; sequence?: number }

export type OpenClawChatOptions = {
  enabled: boolean
  imageIoEnabled?: boolean
  mediaOrigins?: string[]
  userId: string
  defaultGatewayUrl: string
  vault?: OpenClawCredentialVault
  clientFactory?: (options: OpenClawGatewayClientOptions) => OpenClawClientPort
}

export type OpenClawChatState = {
  gatewayUrl: string
  status: OpenClawConnectionStatus
  toolsStatus: OpenClawToolsStatus
  messages: OpenClawChatMessage[]
  streamText: string
  streamCreatedAt: number | null
  runTrace: OpenClawRunTrace | null
  issue: OpenClawSetupIssue | null
  runtimeIssue: string | null
  modelSwitchFallback: OpenClawModelSwitchFallback | null
  contextUsage: OpenClawContextUsage | null
  imageInputAvailable: boolean
  currentModelSupportsImages: boolean
  sessionKey: string | null
  isRunning: boolean
  isStopping: boolean
  reconnectAttempt: number
  runtimeLoading: boolean
  runtimeUpdating: boolean
  models: OpenClawModelOption[]
  thinkingOptions: OpenClawThinkingOption[]
  runtimeSelection: OpenClawRuntimeSelection
}

export type OpenClawChatController = OpenClawChatState & {
  setGatewayUrl(value: string): void
  connect(authInput?: string, requestedUrl?: string): Promise<boolean>
  retryConnection(): void
  disconnect(): void
  clearTranscript(): void
  forget(): Promise<void>
  send(request: OpenClawSendRequest): Promise<boolean>
  retry(messageId: string): Promise<boolean>
  takeFailedMessage(messageId: string): OpenClawSendRequest | null
  refreshMedia(messageId: string, imageId: string): Promise<void>
  stop(): Promise<void>
  setModel(modelId: string | null): Promise<boolean>
  setThinking(thinkingLevel: string | null): Promise<boolean>
  switchToBlankConversation(): Promise<boolean>
  newConversation(): Promise<boolean>
}
