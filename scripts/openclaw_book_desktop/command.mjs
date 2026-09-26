import {createHash} from 'node:crypto';

export const ROOT = '/home/ubuntu/.openclaw/workspace/skills/book-skill/scripts/';
export const TASK_ROOT = '/tmp/openclaw/downloads/book-skill';
export const LEASE = '/home/ubuntu/.local/bin/openclaw-computer-lease';
export const OPS = ['start', 'select', 'await', 'back', 'status', 'visual_next', 'visual_read', 'visual_submit', 'renew', 'release'];

function value(input, key, pattern, max = 300) {
  const text = input[key];
  if (typeof text !== 'string' || !text || text.length > max || /[\x00-\x1f]/.test(text) || (pattern && !pattern.test(text))) {
    throw new Error(`Invalid ${key}`);
  }
  return text;
}

export function taskIdentity(context, input) {
  if (!/^ih-[a-f0-9]{32}$/.test(context.agentId ?? '') ||
      !context.sessionKey?.startsWith(`agent:${context.agentId}:`) || !context.sessionId) {
    throw new Error('Personal Agent conversation identity required');
  }
  const task = value(input, 'task', /^[a-z0-9][a-z0-9-]{0,39}$/);
  const hash = createHash('sha256').update(JSON.stringify([context.agentId, context.sessionKey, context.sessionId, task])).digest('hex');
  return `book-ih-${hash.slice(0, 48)}`;
}

export function command(task, input) {
  if (!OPS.includes(input.operation)) throw new Error('Unsupported operation');
  const op = input.operation;
  if (op === 'visual_read') return null;
  if (['renew', 'release'].includes(op)) return [LEASE, [op, task]];
  if (op === 'visual_submit') {
    const challenge = value(input, 'challengeId', /^[A-Za-z0-9-]+$/, 100);
    const first = value(input, 'first', /^[A-Za-z0-9]{5}$/, 5);
    const second = value(input, 'second', /^[A-Za-z0-9]{5}$/, 5);
    if (first !== second) throw new Error('Independent readings disagree; preserve task');
    return ['/usr/bin/python3', [ROOT + 'visual_flow.py', '--task-id', task, 'submit', '--challenge-id', challenge, '--first', first, '--second', second]];
  }
  if (op === 'visual_next') return ['/usr/bin/python3', [ROOT + 'visual_flow.py', '--task-id', task, 'next', '--target', value(input, 'targetId', /^[A-Fa-f0-9]{32}$/)]];
  const args = [ROOT + 'book_browser.mjs', task, op];
  if (op === 'start') {
    args.push(value(input, 'title', null, 500));
    for (const key of ['language', 'format', 'edition']) {
      if (input[key] !== undefined) args.push(`--${key}`, value(input, key, key === 'format' ? /^(pdf|epub|mobi|azw|azw3)$/ : null));
    }
  } else if (op !== 'status') {
    args.push(value(input, 'targetId', /^[A-Fa-f0-9]{32}$/));
    if (op === 'select') args.push(value(input, 'ref', /^l[0-9]+$/));
  }
  return ['/usr/bin/node', args];
}
