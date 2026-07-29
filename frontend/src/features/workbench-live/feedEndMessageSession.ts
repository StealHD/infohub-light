import type { FeedEndMessageScene, FeedEndMessages } from '../../api/types'

const storagePrefix = 'inteliscope.feed-end-messages.v1.'

export const builtinFeedEndMessages: FeedEndMessages['scenes'] = {
  empty: [
    '这里暂时很安静。🌿',
    '这一页目前没有可显示的内容。',
    '先留一点空白，换个条件再看看。',
  ],
  first_end: [
    '这一轮内容先到这里。☕',
    '当前列表已经走到末尾。',
    '先停在这里，让信息沉淀一下。',
  ],
  repeat_end: [
    '又到末尾了。^_^',
    '还是这里，当前列表没有更多内容。',
    '这次也到底了，先去别处看看。',
  ],
}

type FeedEndMessageSession = {
  endVisits: number
  lastByScene: Partial<Record<FeedEndMessageScene, string>>
}

const emptySession = (): FeedEndMessageSession => ({ endVisits: 0, lastByScene: {} })
const storageKey = (userId: string) => `${storagePrefix}${userId}`

function readSession(userId: string): FeedEndMessageSession {
  if (typeof window === 'undefined') return emptySession()
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(storageKey(userId)) || '{}') as Partial<FeedEndMessageSession>
    return {
      endVisits: Number.isInteger(parsed.endVisits) && Number(parsed.endVisits) >= 0
        ? Number(parsed.endVisits)
        : 0,
      lastByScene: parsed.lastByScene && typeof parsed.lastByScene === 'object'
        ? parsed.lastByScene
        : {},
    }
  } catch {
    return emptySession()
  }
}

function writeSession(userId: string, session: FeedEndMessageSession): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(storageKey(userId), JSON.stringify(session))
  } catch {
    // Session storage can be unavailable in privacy modes; copy still works in-memory.
  }
}

function chooseWithoutImmediateRepeat(
  messages: string[],
  previous: string | undefined,
  random: () => number,
): string {
  const usable = messages.filter((message) => message.trim())
  if (!usable.length) return ''
  const candidates = usable.length > 1 && previous
    ? usable.filter((message) => message !== previous)
    : usable
  const index = Math.min(
    candidates.length - 1,
    Math.max(0, Math.floor(random() * candidates.length)),
  )
  return candidates[index] ?? candidates[0] ?? ''
}

export function selectEmptyFeedMessage(
  userId: string,
  messages: string[],
  random: () => number = Math.random,
): string {
  const session = readSession(userId)
  const selected = chooseWithoutImmediateRepeat(messages, session.lastByScene.empty, random)
  session.lastByScene.empty = selected
  writeSession(userId, session)
  return selected
}

export function selectTerminalFeedMessage(
  userId: string,
  scenes: FeedEndMessages['scenes'],
  random: () => number = Math.random,
): { scene: 'first_end' | 'repeat_end'; message: string } {
  const session = readSession(userId)
  const scene = session.endVisits === 0 ? 'first_end' : 'repeat_end'
  const selected = chooseWithoutImmediateRepeat(
    scenes[scene],
    session.lastByScene[scene],
    random,
  )
  session.endVisits += 1
  session.lastByScene[scene] = selected
  writeSession(userId, session)
  return { scene, message: selected }
}

export function clearFeedEndMessageSession(userId: string): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.removeItem(storageKey(userId))
  } catch {
    // Nothing else needs clearing when browser storage is unavailable.
  }
}
