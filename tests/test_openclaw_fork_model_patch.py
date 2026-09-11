import json
import subprocess

import pytest

from scripts.patch_openclaw_fork_model import ANCHOR, PIN, patch_package


@pytest.mark.parametrize('version', ['2026.9.2', '2026.9.3'])
def test_patch_is_explicit_idempotent_and_keeps_context(tmp_path, version):
    (tmp_path / 'dist').mkdir()
    (tmp_path / 'package.json').write_text(json.dumps({'name': 'openclaw', 'version': version}))
    target = tmp_path / 'dist/session-create-service-fixture.mjs'
    original = 'if (params.fork !== true) return;\nconst forkParentSessionKey = canonicalParentSessionKey;\n' + ANCHOR
    target.write_text(original)
    assert patch_package(tmp_path)['status'] == 'ready'
    assert target.read_text() == original
    assert patch_package(tmp_path, True)['status'] == 'patched_restart_required'
    assert patch_package(tmp_path, True)['status'] == 'already_patched'
    assert len(list((tmp_path / 'dist').glob('*.bak'))) == 1
    # Run the exact inserted JavaScript. Parent/context metadata and no-model
    # inheritance remain untouched; explicit default selection becomes pinned.
    program = '''const normalizeOptionalString = value => value?.trim();
const childModel = { provider: 'deepseek', model: 'flash' };
for (const model of [undefined, 'deepseek/flash']) {
 const params = {model}; const entry = {parentSessionKey:'gemini-parent', transcript:['prior context']};
''' + PIN + '''
 if (entry.parentSessionKey !== 'gemini-parent' || entry.transcript[0] !== 'prior context') throw Error('context lost');
 if (model && (entry.providerOverride !== 'deepseek' || entry.modelOverride !== 'flash' || entry.modelOverrideSource !== 'user')) throw Error('model not pinned');
 if (!model && entry.modelOverride) throw Error('implicit inheritance changed');
}'''
    subprocess.run(['node', '--input-type=module', '-e', program], check=True, capture_output=True)


def test_unknown_package_refuses_without_writes(tmp_path):
    (tmp_path / 'package.json').write_text('{"name":"openclaw","version":"future"}')
    with pytest.raises(ValueError, match='reviewed'):
        patch_package(tmp_path, True)
    assert list(tmp_path.iterdir()) == [tmp_path / 'package.json']
