import type { ReactNode } from 'react'
import type { OpenClawChatController } from '../openclawContracts'
import { OpenClawWorkspaceRuntimeContext } from './openClawWorkspaceRuntimeContext'

export function OpenClawWorkspaceRuntimeProvider({ chat, children }: { chat: OpenClawChatController; children: ReactNode }) { return <OpenClawWorkspaceRuntimeContext.Provider value={chat}>{children}</OpenClawWorkspaceRuntimeContext.Provider> }
