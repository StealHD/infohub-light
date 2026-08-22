import {
  type OpenClawCredentialAdapter,
  type StoredOpenClawCredential,
} from './openclawCredentialVault'

export class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  puts: StoredOpenClawCredential[] = []
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => {
    this.puts.push(value)
    this.values.set(value.id, value)
  }
  delete = async (key: string) => { this.values.delete(key) }
}

export const models = {
  models: [
    { id: 'gpt-5.4', name: 'GPT-5.4', provider: 'openai', available: true, contextWindow: 200_000, reasoning: true },
    { id: 'deep', name: 'Deep', provider: 'openai', available: true, contextWindow: 160_000, reasoning: true },
    { id: 'quick', name: 'Quick', provider: 'local', available: true, contextWindow: 32_000, reasoning: false },
  ],
}
export const agents = {
  defaultId: 'main',
  agents: [{
    id: 'main',
    model: { primary: 'openai/gpt-5.4' },
    thinkingLevels: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
    thinkingDefault: 'low',
  }],
}
export const session = {
  session: {
    modelProvider: 'openai',
    model: 'gpt-5.4',
    thinkingLevel: 'high',
    thinkingLevels: agents.agents[0].thinkingLevels,
    thinkingDefault: 'low',
  },
}
