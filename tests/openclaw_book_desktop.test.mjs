import test from 'node:test';
import assert from 'node:assert/strict';
import {taskIdentity, command, ROOT, LEASE} from '../scripts/openclaw_book_desktop/command.mjs';
import {createTool} from '../scripts/openclaw_book_desktop/index.mjs';
import {validatePanelPath, recoverableFailure} from '../scripts/openclaw_book_desktop/runtime.mjs';

const agentId = 'ih-' + 'a'.repeat(32);
function context(session = 'first') {
  return {agentId, sessionKey: `agent:${agentId}:dashboard:${session}`, sessionId: session,
    config: {agents: {entries: {[agentId]: {skills: ['book-skill'], tools: {allow: ['book_desktop']}}}}}};
}
const input = {task: 'little-prince', operation: 'start', title: '小王子'};

test('native content-hashed reading panels stay within the exact task and challenge', () => {
  const challenge = 'a'.repeat(32), digest = 'b'.repeat(64);
  const path = `/tmp/openclaw/downloads/book-skill/book-own/panels-${challenge}/${digest}/reading.png`;
  assert.doesNotThrow(() => validatePanelPath('book-own', challenge, path));
  assert.throws(() => validatePanelPath('book-other', challenge, path));
  assert.throws(() => validatePanelPath('book-own', 'c'.repeat(32), path));
  assert.throws(() => validatePanelPath('book-own', challenge, path.replace('reading.png', 'channels.png')));
  assert.throws(() => validatePanelPath('book-own', challenge, path.replace(digest, '../../other')));
});

test('desktop task identity is stable but isolated across sessions and resets', () => {
  const c = context();
  assert.equal(taskIdentity(c, input), taskIdentity(c, input));
  assert.notEqual(taskIdentity(c, input), taskIdentity(context('second'), input));
  assert.notEqual(taskIdentity(c, input), taskIdentity({...c, sessionId: 'reset'}, input));
  assert.throws(() => taskIdentity({...c, sessionKey: 'agent:main:secret'}, input));
  assert.throws(() => taskIdentity({...c, sessionId: undefined}, input));
  assert.throws(() => taskIdentity(c, {...input, task: '../other'}));
});

test('user text remains one literal argument to a fixed script', () => {
  const title = 'Book $(touch /tmp/no) ; "quoted"';
  const [binary, args] = command('book-test', {...input, title});
  assert.equal(binary, '/usr/bin/node');
  assert.deepEqual(args, [ROOT + 'book_browser.mjs', 'book-test', 'start', title]);
  assert.throws(() => command('book-test', {...input, operation: 'exec'}));
  assert.throws(() => command('book-test', {...input, operation: 'select', targetId: '../other', ref: 'l1'}));
});

test('lost lease is a recoverable state without exposing helper stderr', () => {
  const expected = {phase: 'lease_lost', next: 'status_then_resume_start'};
  assert.deepEqual(recoverableFailure(LEASE, ['renew', 'book-task'], 'not-owner\n', ''), expected);
  assert.deepEqual(recoverableFailure('/usr/bin/python3', ['visual_flow.py'], '',
    'ValueError: active desktop lease required for exact task ID'), expected);
  assert.equal(recoverableFailure('/usr/bin/python3', ['visual_flow.py'], '',
    'private browser output'), null);
});

test('visual preparation reacquires the same task lease before acting', async () => {
  const targetId = 'A'.repeat(32), calls = [];
  const tool = createTool(context('recover-lease'), {executeFile: async (binary, args) => {
    const operation = binary === LEASE ? args[0] : args[0].endsWith('visual_flow.py') ? 'visual_next' : args[2];
    calls.push(operation);
    if (operation === 'renew') return {phase: 'lease_lost'};
    if (operation === 'status') return {phase: 'verification', target: targetId,
      actionUncertain: false, request: {title: '小王子', language: 'zh', operation: 'release'}};
    if (operation === 'start') {
      assert.equal(args[3], '小王子');
      assert.deepEqual(args.slice(4), ['--language', 'zh']);
      return {phase: 'verification', target: targetId, hostReady: true};
    }
    return {status: 'passed'};
  }});
  const result = await tool.execute('recover', {...input, operation: 'visual_next', targetId});
  assert.deepEqual(calls, ['renew', 'status', 'start', 'visual_next']);
  assert.equal(result.details.status, 'passed');
});

test('visual recovery stops before action when checkpoint is uncertain or desktop is busy', async () => {
  const targetId = 'B'.repeat(32);
  for (const uncertain of [true, false]) {
    const calls = [];
    const tool = createTool(context(`recover-${uncertain}`), {executeFile: async (binary, args) => {
      const operation = binary === LEASE ? args[0] : args[2];
      calls.push(operation);
      if (operation === 'renew') return {phase: 'lease_lost'};
      if (operation === 'status') return {phase: 'verification', target: targetId,
        actionUncertain: uncertain, request: {title: '小王子'}};
      return {phase: 'busy', next: 'wait_for_desktop'};
    }});
    const result = await tool.execute('recover', {...input, operation: 'visual_next', targetId});
    assert.deepEqual(calls, uncertain ? ['renew', 'status'] : ['renew', 'status', 'start']);
    assert.equal(result.details.phase, uncertain ? 'resume_required' : 'busy');
  }
});

test('visual recovery never acts on a changed target', async () => {
  const targetId = 'C'.repeat(32), calls = [];
  const tool = createTool(context('changed-target'), {executeFile: async (binary, args) => {
    const operation = binary === LEASE ? args[0] : args[2];
    calls.push(operation);
    if (operation === 'renew') return {phase: 'lease_lost'};
    return {phase: 'verification', target: 'D'.repeat(32), request: {title: '小王子'}};
  }});
  const result = await tool.execute('recover', {...input, operation: 'visual_next', targetId});
  assert.deepEqual(calls, ['renew', 'status']);
  assert.equal(result.details.phase, 'resume_required');
});

test('a lease lost during visual preparation is reported without replaying the action', async () => {
  const targetId = 'E'.repeat(32), calls = [];
  const tool = createTool(context('lost-during-action'), {executeFile: async (binary, args) => {
    calls.push(binary === LEASE ? 'renew' : 'visual_next');
    return binary === LEASE ? {status: 'renewed'} : {phase: 'lease_lost'};
  }});
  const result = await tool.execute('visual', {...input, operation: 'visual_next', targetId});
  assert.deepEqual(calls, ['renew', 'visual_next']);
  assert.equal(result.details.phase, 'lease_lost');
});

test('revoked authorization fails before any native script runs', async () => {
  const c = context(); let calls = 0;
  const tool = createTool(c, {executeFile: async () => { calls++; return {}; }});
  await tool.execute('first', input);
  c.config.agents.entries[agentId].skills = [];
  await assert.rejects(tool.execute('second', input), /not authorized/);
  assert.equal(calls, 1);
});

test('two image returns precede one submission; failed reads and duplicate submits do not count', async () => {
  let fail = true; let submissions = 0;
  const tool = createTool(context('visual'), {
    reading: async () => { if (fail) throw Error('missing image'); return {type: 'image', data: 'test', mimeType: 'image/png'}; },
    challengeRecord: async () => ({}),
    executeFile: async () => { submissions++; return {status: 'passed'}; },
  });
  const read = {...input, operation: 'visual_read', challengeId: 'a'.repeat(32)};
  const submit = {...read, operation: 'visual_submit', first: 'Ab123', second: 'Ab123'};
  await assert.rejects(tool.execute('read0', read), /missing image/);
  await assert.rejects(tool.execute('submit0', submit), /Two separate/);
  fail = false;
  await tool.execute('read1', read);
  await assert.rejects(tool.execute('submit1', submit), /Two separate/);
  await tool.execute('read2', read);
  await assert.rejects(tool.execute('read3', read), /Two readings/);
  await assert.rejects(tool.execute('mismatch', {...submit, second: 'ab123'}), /disagree/);
  await tool.execute('submit2', submit);
  await assert.rejects(tool.execute('duplicate', submit), /Two separate/);
  assert.equal(submissions, 1);
});

test('uncertain native submission cannot be replayed with old read receipts', async () => {
  const tool = createTool(context('uncertain'), {
    reading: async () => ({type: 'image', data: 'test', mimeType: 'image/png'}),
    challengeRecord: async () => ({}), executeFile: async () => { throw Error('connection lost'); },
  });
  const read = {...input, operation: 'visual_read', challengeId: 'b'.repeat(32)};
  await tool.execute('read1', read); await tool.execute('read2', read);
  const submit = {...read, operation: 'visual_submit', first: 'Ab123', second: 'Ab123'};
  await assert.rejects(tool.execute('submit', submit), /connection lost/);
  await assert.rejects(tool.execute('repeat', submit), /Two separate/);
});

test('lost lease never replays a submitted challenge', async () => {
  let submissions = 0;
  const tool = createTool(context('submit-lease-lost'), {
    reading: async () => ({type: 'image', data: 'test', mimeType: 'image/png'}),
    challengeRecord: async () => ({}),
    executeFile: async () => { submissions++; return {phase: 'lease_lost'}; },
  });
  const read = {...input, operation: 'visual_read', challengeId: 'c'.repeat(32)};
  await tool.execute('read1', read); await tool.execute('read2', read);
  const submit = {...read, operation: 'visual_submit', first: 'Ab123', second: 'Ab123'};
  assert.equal((await tool.execute('submit', submit)).details.phase, 'lease_lost');
  await assert.rejects(tool.execute('repeat', submit), /Two separate/);
  assert.equal(submissions, 1);
});

test('parallel calls on one task cannot run two native operations', async () => {
  let done;
  const tool = createTool(context('parallel'), {executeFile: () => new Promise(resolve => { done = resolve; })});
  const first = tool.execute('first', input);
  await assert.rejects(tool.execute('second', input), /in progress/);
  done({phase: 'search'}); await first;
});
