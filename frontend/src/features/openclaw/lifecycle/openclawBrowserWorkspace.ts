import { useMemo } from 'react'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { createOpenClawWorkspaceRuntime } from '../workspace/openclawWorkspaceRuntime'
import { isManagedGateway } from '../gateway/openclawManaged'
import { saveManagedSession } from '../storage/openclawManagedSession'
import { clearOpenClawTranscript } from '../storage/openclawTranscriptStore'

export function useBrowserWorkspace(refs: OpenClawLifecycleRefs, userId: string, getGatewayUrl: () => string) {
  return useMemo(() => createOpenClawWorkspaceRuntime(refs, (deletedKey) => {
    const gatewayUrl = getGatewayUrl()
    clearOpenClawTranscript(userId, gatewayUrl, deletedKey)
    if (isManagedGateway(gatewayUrl) && refs.session.sessionKey) saveManagedSession(userId, refs.session.sessionKey)
  }), [refs, userId, getGatewayUrl])
}
