import {execFile} from 'node:child_process';
import {open, realpath} from 'node:fs/promises';
import {constants} from 'node:fs';
import {resolve} from 'node:path';
import {TASK_ROOT, LEASE} from './command.mjs';

export function executeFile(binary, args, signal) {
  return new Promise((accept, reject) => {
    execFile(binary, args, {timeout: 180000, maxBuffer: 512 * 1024, signal, shell: false}, (error, stdout) => {
      if (error) return reject(new Error('Desktop helper did not finish successfully; preserve task and inspect status before retrying'));
      try {
        if (binary === LEASE && ['renewed', 'released'].includes(stdout.trim())) return accept({status: stdout.trim()});
        const lines = stdout.trim().split('\n').filter(Boolean);
        accept(JSON.parse(lines.at(-1)));
      } catch { reject(new Error('Desktop helper returned an invalid result; preserve task')); }
    });
  });
}

export async function privateFile(path, maximum) {
  if (await realpath(path) !== resolve(path)) throw new Error('Symlink in task path');
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const st = await file.stat();
    if (!st.isFile() || st.uid !== process.getuid() || (st.mode & 0o077) || st.size > maximum) throw new Error('Unsafe task file');
    return await file.readFile();
  } finally { await file.close(); }
}

export async function challengeRecord(task, challengeId) {
  const dir = `${TASK_ROOT}/${task}`;
  const state = JSON.parse(await privateFile(`${dir}/visual-step.json`, 1024 * 1024));
  const record = state.rounds?.at(-1);
  if (record?.id !== challengeId || record.status !== 'prepared' || state.status !== 'prepared') throw new Error('Stale or unsettled challenge');
  const path = record.result?.reading_path;
  validatePanelPath(task, challengeId, path);
  return {record, path};
}

export function validatePanelPath(task, challengeId, path) {
  const prefix = `${TASK_ROOT}/${task}/panels-${challengeId}/`;
  if (typeof path !== 'string' || !/^[a-f0-9]{32}$/.test(challengeId) ||
      !resolve(path).startsWith(prefix) || !/^[a-f0-9]{64}\/reading\.png$/.test(resolve(path).slice(prefix.length))) {
    throw new Error('Invalid reading panel');
  }
}

export async function reading(task, challengeId) {
  const {path} = await challengeRecord(task, challengeId);
  const bytes = await privateFile(path, 4 * 1024 * 1024);
  if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error('Expected PNG reading panel');
  return {type: 'image', data: bytes.toString('base64'), mimeType: 'image/png'};
}
