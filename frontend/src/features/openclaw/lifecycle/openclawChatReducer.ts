import type {
  OpenClawChatMessage,
  OpenClawChatState,
  OpenClawConnectionStatus,
  OpenClawRunTrace,
  OpenClawRuntimeSelection,
} from '../openclawContracts'

export type OpenClawLifecycleState = OpenClawChatState & {
  runId: string | null
  sending: boolean
  stopping: boolean
}

export type OpenClawChatAction =
  | { type: 'patch'; value: Partial<OpenClawLifecycleState> }
  | { type: 'messages'; value: OpenClawChatMessage[] }
  | { type: 'run-trace'; value: OpenClawRunTrace | null }
  | { type: 'runtime-selection'; value: OpenClawRuntimeSelection }

export type OpenClawChatDispatch = (action: OpenClawChatAction) => void

const EMPTY_RUNTIME_SELECTION: OpenClawRuntimeSelection = {
  modelId: null,
  thinkingLevel: null,
  defaultModelId: null,
  defaultThinkingLevel: null,
}

export function createOpenClawChatState(
  gatewayUrl: string,
  status: OpenClawConnectionStatus,
): OpenClawLifecycleState {
  return {
    gatewayUrl,
    status,
    toolsStatus: 'unknown',
    messages: [],
    streamText: '',
    streamCreatedAt: null,
    runTrace: null,
    issue: null,
    runtimeIssue: null,
    modelSwitchFallback: null,
    contextUsage: null,
    imageInputAvailable: false,
    currentModelSupportsImages: false,
    sessionKey: null,
    isRunning: false,
    isStopping: false,
    reconnectAttempt: 0,
    runtimeLoading: false,
    runtimeUpdating: false,
    models: [],
    thinkingOptions: [],
    runtimeSelection: EMPTY_RUNTIME_SELECTION,
    runId: null,
    sending: false,
    stopping: false,
  }
}

export function openClawChatReducer(
  state: OpenClawLifecycleState,
  action: OpenClawChatAction,
): OpenClawLifecycleState {
  if (action.type === 'messages') return { ...state, messages: action.value }
  if (action.type === 'run-trace') return { ...state, runTrace: action.value }
  if (action.type === 'runtime-selection') return { ...state, runtimeSelection: action.value }
  return { ...state, ...action.value }
}

export function resetOpenClawRuntimeState(): Partial<OpenClawLifecycleState> {
  return {
    sessionKey: null,
    models: [],
    thinkingOptions: [],
    runtimeSelection: EMPTY_RUNTIME_SELECTION,
    runtimeLoading: false,
    runtimeUpdating: false,
    runtimeIssue: null,
    modelSwitchFallback: null,
    contextUsage: null,
  }
}
