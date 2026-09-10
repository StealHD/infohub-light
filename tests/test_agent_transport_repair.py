"""Repair only exact historical managed configuration, preserving revocation."""
import copy

import pytest

from tests.test_agent_connections import personal
from src.services.agent_connections.gateway_config import configure, compatible_mcp


def test_missing_transport_and_memory_policy_are_repaired_without_other_changes(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://localhost:8080/mcp')
    target = configure({}, manifest, tmp_path)
    old = copy.deepcopy(target)
    old['mcp']['servers'][manifest['mcp_server']].pop('transport')
    old['agents']['entries'][manifest['agent_id']].pop('memorySearch')
    assert compatible_mcp(old['mcp']['servers'][manifest['mcp_server']], manifest)
    assert configure(old, manifest, tmp_path) == target
    assert target['mcp']['servers'][manifest['mcp_server']]['transport'] == 'streamable-http'
    assert target['agents']['entries'][manifest['agent_id']]['memorySearch'] == {'enabled': False}
    assert 'memorySearch' not in target['agents']['entries']['main']


def test_explicit_transport_drift_is_not_silently_overwritten(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://localhost:8080/mcp')
    config = configure({}, manifest, tmp_path)
    config['mcp']['servers'][manifest['mcp_server']]['transport'] = 'sse'
    assert not compatible_mcp(config['mcp']['servers'][manifest['mcp_server']], manifest)
    with pytest.raises(ValueError, match='MCP'):
        configure(config, manifest, tmp_path)
