import {OPS, taskIdentity, command} from './command.mjs';
import {executeFile, challengeRecord, reading} from './runtime.mjs';

const counts = new Map();
const running = new Set();
const string = {type: 'string'};
const parameters = {type: 'object', additionalProperties: false, required: ['operation', 'task'], properties: {
  operation: {type: 'string', enum: OPS}, task: {...string, description: 'Stable short label for this book; reuse on follow-up. Never supply a server task ID.'},
  title: string, language: string, format: {type: 'string', enum: ['pdf', 'epub', 'mobi', 'azw', 'azw3']}, edition: string,
  targetId: string, ref: string, challengeId: string, first: string, second: string,
}};

export function authorized(context) {
  const config = context.getRuntimeConfig?.() ?? context.runtimeConfig ?? context.config;
  const agent = config?.agents?.entries?.[context.agentId];
  return agent?.skills?.includes('book-skill') && agent?.tools?.allow?.includes('book_desktop') &&
    !agent?.tools?.deny?.some(rule => ['book_desktop', '*', 'inteliscope-book-desktop'].includes(rule));
}

export function createTool(context, deps = {executeFile, challengeRecord, reading}) {
  return {name: 'book_desktop', label: 'Book Skill desktop', parameters,
    description: 'Run the installed book-skill on the VPS desktop Chrome. Reuses native task/lease/checkpoint and visual verification helpers. Read book-skill Project Agents instructions. Verification requires current user authorization. Keep one task label and the returned target; never restart on observation timeout.',
    async execute(_id, input, signal) {
      if (!authorized(context)) throw new Error('Desktop book Skill is not authorized for this Agent');
      const task = taskIdentity(context, input);
      const cmd = command(task, input);
      if (running.has(task)) throw new Error('Task operation in progress; observe before retrying');
      running.add(task);
      try {
        const key = `${task}:${input.challengeId}`;
        if (input.operation === 'visual_read') {
          const count = counts.get(key) ?? 0;
          if (count >= 2) throw new Error('Two readings already returned; preserve challenge');
          const image = await deps.reading(task, input.challengeId);
          counts.set(key, count + 1);
          return {content: [image, {type: 'text', text: `Reading ${count + 1} of 2. Transcribe independently without guessing.`}], details: {reading: count + 1}};
        }
        if (input.operation === 'visual_submit') {
          await deps.challengeRecord(task, input.challengeId);
          if (counts.get(key) !== 2) throw new Error('Two separate successful image reads are required before submit');
          counts.delete(key);
        }
        const result = await deps.executeFile(...cmd, signal);
        if (result.reading_path && result.challenge_id) {
          delete result.reading_path;
          result.instruction = 'Call book_desktop visual_read twice with this task label and challengeId. Independently transcribe each image. If both five-character readings agree exactly, use visual_submit. Do not use exec, read or view_image for these task files.';
        }
        if (input.operation === 'release') for (const key of counts.keys()) if (key.startsWith(task + ':')) counts.delete(key);
        return {content: [{type: 'text', text: JSON.stringify(result)}], details: result};
      } finally { running.delete(task); }
    },
  };
}

export default {id: 'inteliscope-book-desktop', name: 'Inscope desktop book workflow', register(api) {
  api.registerTool(context => /^ih-[a-f0-9]{32}$/.test(context.agentId ?? '') ? createTool(context) : null,
    {optional: true, names: ['book_desktop']});
}};
