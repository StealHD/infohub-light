import json

import pytest

from scripts.patch_openclaw_codex_model_list_timeout import (
    CALL_ANCHOR, CALL_PATCH, DEADLINE_ANCHOR, DEADLINE_PATCH, patch_package,
)


def package(tmp_path, *, version='2026.9.3', source=None):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (tmp_path / 'package.json').write_text(json.dumps({'name': '@openclaw/codex', 'version': version}))
    target = dist / 'bounded-turn-fixture.js'
    target.write_text(source or CALL_ANCHOR + '\n' + DEADLINE_ANCHOR)
    return target


def test_only_isolated_completion_gets_longer_model_list_deadline(tmp_path):
    target = package(tmp_path)
    original = target.read_bytes()
    assert patch_package(tmp_path)['status'] == 'ready'
    assert target.read_bytes() == original
    assert patch_package(tmp_path, apply=True)['status'] == 'patched_restart_required'
    updated = target.read_text()
    assert CALL_PATCH in updated and DEADLINE_PATCH in updated
    assert 'params.taskLabel === "isolated completion" ? 30e3 : 5e3' in updated
    assert patch_package(tmp_path, apply=True)['status'] == 'already_patched'
    assert len(list((tmp_path / 'dist').glob('*.bak'))) == 1


@pytest.mark.parametrize('version,source', [
    ('future', CALL_ANCHOR + '\n' + DEADLINE_ANCHOR),
    ('2026.9.3', 'different implementation'),
    ('2026.9.3', CALL_ANCHOR + '\n' + DEADLINE_ANCHOR + '\nmodelListTimeoutMs: unexpected'),
])
def test_unreviewed_package_or_source_is_untouched(tmp_path, version, source):
    target = package(tmp_path, version=version, source=source)
    with pytest.raises(ValueError):
        patch_package(tmp_path, apply=True)
    assert target.read_text() == source
    assert not list((tmp_path / 'dist').glob('*.bak'))
