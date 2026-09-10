"""Opt-in installed-schema checks, separate from controlled Gateway fixtures."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from tests.test_agent_connections import personal  # noqa: F401
from src.services.agent_connections.gateway_config import configure
from src.services.agent_connections.connector_config import configure as analysis_config


def native(configs):
    package = os.getenv('INTELISCOPE_OPENCLAW_PACKAGE')
    node = shutil.which('node')
    if not package or not node:
        pytest.skip('Installed OpenClaw schema not configured; this is not native acceptance')
    script = Path(__file__).resolve().parents[1] / 'scripts/probe_native_config.mjs'
    result = subprocess.run([node, str(script)], input=json.dumps({'packageRoot': package, 'configs': configs}),
                            text=True, capture_output=True, timeout=20)
    assert result.stderr == ''
    data = json.loads(result.stdout)
    assert (result.returncode == 0) == data['valid']
    return data


def test_actual_schema_accepts_new_and_repaired_personal_and_analysis(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://localhost:8080/mcp')
    target = configure({}, manifest, tmp_path)
    legacy = copy.deepcopy(target)
    legacy['agents']['entries'][manifest['agent_id']].pop('memory')
    legacy['mcp']['servers'][manifest['mcp_server']].pop('transport')
    repaired = configure(legacy, manifest, tmp_path)
    analysis, identity = analysis_config(repaired, manifest, tmp_path)
    old_analysis = copy.deepcopy(analysis)
    old_analysis['agents']['entries'][identity].pop('memory')
    again, _ = analysis_config(old_analysis, manifest, tmp_path)
    assert native([target, repaired, analysis, again])['valid']


def test_actual_schema_rejects_the_pre_fix_field(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://localhost:8080/mcp')
    target = configure({}, manifest, tmp_path)
    entry = target['agents']['entries'][manifest['agent_id']]
    entry['memorySearch'] = entry.pop('memory')['search']
    result = native([target])
    assert not result['valid']
    assert any(item['path'] == ['agents', 'entries', manifest['agent_id']] for item in result['failures'])
