from copy import deepcopy

import pytest

from src.services.agent_connections.gateway_config import DENIED, configure
from src.services.agent_connections.skill_tools import required_skill_tools, skill_tool_policy
from tests.test_agent_connections import personal  # noqa: F401


def test_skill_tools_are_minimal_idempotent_and_revoked_with_selection():
    original = {'allow': ['own__get_item'], 'deny': [*DENIED, 'other__*'], 'profile': 'full'}
    before = deepcopy(original)
    enabled = skill_tool_policy(original, ['book-skill'])
    assert original == before
    assert enabled == skill_tool_policy(enabled, ['book-skill'])
    assert enabled['allow'] == ['own__get_item', 'read', 'browser']
    assert enabled['fs'] == {'workspaceOnly': True}
    assert {'write', 'edit', 'apply_patch', 'exec', 'process', 'other__*', 'canvas', 'computer'} <= set(enabled['deny'])
    assert not {'read', 'browser', 'group:fs', 'group:ui'} & set(enabled['deny'])
    reader = skill_tool_policy(enabled, ['reader'])
    assert reader['allow'] == ['own__get_item', 'read']
    assert {'browser', 'group:ui'} <= set(reader['deny'])
    closed = skill_tool_policy(reader, [])
    assert closed['allow'] == ['own__get_item']
    assert {'read', 'browser', 'group:fs', 'group:ui'} <= set(closed['deny'])
    assert closed['profile'] == 'full'


@pytest.mark.parametrize('keys,expected', [([], []), (['reader'], ['read']),
                                         (['book-skill'], ['read', 'browser'])])
def test_initial_provisioning_and_legacy_repair_share_the_skill_policy(personal, tmp_path, keys, expected):
    _, connections, owner, _ = personal
    manifest = {**connections.prepare(owner['id'], 'http://localhost:8080/mcp'), 'skills': keys}
    target = configure({}, manifest, tmp_path)
    entry = target['agents']['entries'][manifest['agent_id']]
    assert required_skill_tools(keys) == expected
    assert all(tool in entry['tools']['allow'] for tool in expected)
    assert entry['tools']['fs'] == {'workspaceOnly': True}
    legacy = deepcopy(target)
    old = legacy['agents']['entries'][manifest['agent_id']]['tools']
    old.pop('fs')
    old['allow'] = [tool for tool in old['allow'] if tool not in {'read', 'browser'}]
    old['deny'] = list(DENIED)
    assert configure(legacy, manifest, tmp_path) == target
    assert configure(target, manifest, tmp_path) == target


def test_skill_tools_reject_implicit_allowlists():
    with pytest.raises(ValueError):
        skill_tool_policy({'profile': 'full'}, ['book-skill'])
