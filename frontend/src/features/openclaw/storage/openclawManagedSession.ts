import type { StoredOpenClawCredential } from '../openclawCredentialVault'

const key = (userId: string) => `infohub-managed-session:${userId}`
type ManagedSession = Partial<StoredOpenClawCredential>

export async function managedSession(userId: string): Promise<ManagedSession> {
  let sessionKey: string | undefined
  try { sessionKey = sessionStorage.getItem(key(userId)) || undefined } catch { /* memory-only session */ }
  return { sessionKey }
}

export function saveManagedSession(userId: string, sessionKey: string): void {
  try { sessionStorage.setItem(key(userId), sessionKey) } catch { /* active session remains usable */ }
}
