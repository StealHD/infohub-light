"""Opt-in execution of the installed Gateway's real workspace/Skill read guard."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROBE = r"""
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const dist = join(input.packageRoot, 'dist');
const candidates = [];
for (const name of await readdir(dist)) {
  if (!/^core-coding-tools-[\w-]+\.m?js$/.test(name)) continue;
  const source = await readFile(join(dist, name), 'utf8');
  const alias = source.match(/\bcreateCoreCodingTools as (\w+)\b/)?.[1];
  if (alias) candidates.push({ name, alias });
}
if (candidates.length !== 1) throw new Error('Unsupported native tool module');
const {name, alias} = candidates[0];
const create = (await import(pathToFileURL(join(dist, name)).href))[alias];
const tools = create({codingRoot: input.workspace, containmentRoot: input.workspace,
  workspaceOnly: true, includeBaseCodingTools: true, includeShellTools: false,
  readOnly: true, skillsSnapshot: {resolvedSkills: [{name: 'book-skill',
    baseDir: input.skillRoot, filePath: join(input.skillRoot, 'SKILL.md')}]} });
const read = tools.find(tool => tool.name === 'read');
if (!read) throw new Error('Missing native read tool');
const results = [];
for (const path of input.paths) {
  try {
    const result = await read.execute('probe', {path});
    results.push({ok: !result.isError, text: result.content?.filter(b => b.type === 'text').map(b => b.text).join('\n')});
  } catch { results.push({ok: false}); }
}
process.stdout.write(JSON.stringify(results));
"""


def test_native_reader_allows_skill_references_but_blocks_other_files_and_symlinks(tmp_path):
    package = os.getenv('INTELISCOPE_OPENCLAW_PACKAGE')
    node = shutil.which('node')
    if not package or not node:
        pytest.skip('Installed OpenClaw not configured; not native acceptance')
    workspace = tmp_path / 'workspace'
    skill = tmp_path / 'skills' / 'book-skill'
    other = tmp_path / 'skills' / 'other'
    for path in (workspace, skill / 'references', other):
        path.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('approved skill instruction')
    (skill / 'references' / 'browser.md').write_text('approved browser reference')
    (other / 'SKILL.md').write_text('unselected skill sentinel')
    secret = tmp_path / 'secret.env'
    secret.write_text('private sentinel')
    (skill / 'escape').symlink_to(secret)
    (workspace / 'escape').symlink_to(secret)
    paths = [skill / 'SKILL.md', skill / 'references' / 'browser.md', secret,
             other / 'SKILL.md', workspace / '..' / 'secret.env', skill / 'escape', workspace / 'escape']
    result = subprocess.run([node, '--input-type=module', '-e', PROBE], input=json.dumps({
        'packageRoot': str(Path(package).resolve()), 'workspace': str(workspace),
        'skillRoot': str(skill), 'paths': [str(path) for path in paths],
    }), text=True, capture_output=True, timeout=30, check=True)
    outcomes = json.loads(result.stdout)
    assert outcomes[0]['ok'] and 'approved skill instruction' in outcomes[0]['text']
    assert outcomes[1]['ok'] and 'approved browser reference' in outcomes[1]['text']
    assert all(not item['ok'] for item in outcomes[2:])
    assert 'private sentinel' not in result.stdout
