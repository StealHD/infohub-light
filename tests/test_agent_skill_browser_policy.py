from copy import deepcopy
import json

import pytest

from scripts import repair_openclaw_browser_policy as cli
from src.services.agent_connections.browser_policy import repaired_browser_policy, repair_browser_policy
from src.services.agent_skill_gateway import AgentSkillGatewayError


@pytest.fixture
def config():
    return {'browser': {'enabled': True, 'headless': True, 'defaultProfile': 'openclaw',
                       'profiles': {'openclaw': {'cdpPort': 18800, 'headless': True}},
                       'ssrfPolicy': {'dangerouslyAllowPrivateNetwork': True,
                                      'blockedHostnames': ['localhost', '*.localhost', '127.0.0.1', '::1',
                                                           '169.254.169.254', 'metadata.google.internal', 'blocked.example']}},
            'agents': {'entries': {'other': {'model': 'unchanged'}}}, 'secret': 'never-print-this'}


def test_conflict_repair_keeps_metadata_and_custom_blocks_and_disables_private_navigation(config):
    before = deepcopy(config)
    target = repaired_browser_policy(config)
    assert target == {'dangerouslyAllowPrivateNetwork': False,
                      'blockedHostnames': ['169.254.169.254', 'metadata.google.internal', 'blocked.example']}
    assert config == before
    config['browser']['ssrfPolicy'] = target
    assert repaired_browser_policy(config) == target


def test_legacy_private_flag_cannot_override_repair(config):
    config['browser']['ssrfPolicy']['allowPrivateNetwork'] = True
    target = repaired_browser_policy(config)
    assert target['allowPrivateNetwork'] is False
    assert target['dangerouslyAllowPrivateNetwork'] is False


@pytest.mark.parametrize('field,value', [
    ('allowedHostnames', ['127.0.0.1']), ('allowedOrigins', ['http://127.0.0.1:8080']),
    ('hostnameAllowlist', ['*.example']), ('allowIpv6UniqueLocalRange', True),
    ('allowRfc2544BenchmarkRange', True), ('unknown', False),
    ('blockedHostnames', '127.0.0.1'), ('blockedHostnames', [3]),
    ('dangerouslyAllowPrivateNetwork', 'true'),
])
def test_custom_trust_and_unknown_policies_fail_closed(config, field, value):
    config['browser']['ssrfPolicy'][field] = value
    with pytest.raises(ValueError):
        repaired_browser_policy(config)


@pytest.mark.parametrize('profile', [
    {'cdpUrl': 'https://remote.example'}, {'driver': 'existing-session'}, {'attachOnly': True},
    {'cdpUrl': 'http://user:password@127.0.0.1:18800'}, {'cdpUrl': 'http://127.0.0.1:18800/path'},
    {'cdpUrl': 42}, [],
])
def test_shared_or_remote_profiles_are_not_silently_reconfigured(config, profile):
    config['browser']['profiles']['other'] = profile
    with pytest.raises(ValueError):
        repaired_browser_policy(config)


def test_nonconflicting_policy_is_unchanged(config):
    config['browser']['ssrfPolicy']['blockedHostnames'] = ['blocked.example']
    assert repaired_browser_policy(config) == config['browser']['ssrfPolicy']


def test_additional_wildcard_block_is_not_claimed_as_repaired(config):
    config['browser']['ssrfPolicy']['blockedHostnames'].append('*.0.0.1')
    with pytest.raises(ValueError):
        repaired_browser_policy(config)


class FakeGateway:
    def __init__(self, config, *, loaded=True, drift=False, uncertain=False):
        self.config, self.calls = deepcopy(config), []
        self.loaded, self.drift, self.uncertain = loaded, drift, uncertain

    async def _session(self, operation):
        return await operation(None, {'features': {'methods': ['config.get', 'config.patch']}})

    async def _request(self, socket, request_id, method, params):
        self.calls.append((method, deepcopy(params)))
        if method == 'config.patch':
            assert params['baseHash'] == 'hash-before'
            assert params['replacePaths'] == ['browser.ssrfPolicy.blockedHostnames']
            patch = json.loads(params['raw'])
            assert set(patch) == {'browser'} and set(patch['browser']) == {'ssrfPolicy'}
            self.config['browser']['ssrfPolicy'] = patch['browser']['ssrfPolicy']
            if self.uncertain:
                raise TimeoutError('raw-upstream-secret')
            return {}
        result = {'hash': 'hash-before', 'config': deepcopy(self.config)}
        if request_id == 'browser-policy-verify':
            if self.drift:
                result['config']['browser']['ssrfPolicy']['dangerouslyAllowPrivateNetwork'] = True
            result.update(configRevisionHash='new', appliedConfigHash='new' if self.loaded else 'old')
        return result


@pytest.mark.anyio
async def test_preview_never_writes_or_returns_config(config):
    gateway = FakeGateway(config)
    result = await repair_browser_policy(gateway)
    assert result['status'] == 'preview' and result['base_hash'] == 'hash-before'
    assert [method for method, _ in gateway.calls] == ['config.get']
    assert 'never-print-this' not in json.dumps(result)


@pytest.mark.anyio
async def test_changed_hash_aborts_without_mutation(config):
    gateway = FakeGateway(config)
    with pytest.raises(ValueError, match='conflict'):
        await repair_browser_policy(gateway, expected_hash='stale')
    assert len(gateway.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize('loaded,status', [(True, 'applied'), (False, 'saved_pending_reload')])
async def test_apply_uses_cas_exact_array_replacement_and_verifies_load(config, loaded, status):
    gateway = FakeGateway(config, loaded=loaded)
    result = await repair_browser_policy(gateway, expected_hash='hash-before')
    assert result['status'] == status
    assert [method for method, _ in gateway.calls] == ['config.get', 'config.patch', 'config.get']
    assert gateway.config['agents'] == config['agents']
    assert gateway.config['secret'] == config['secret']
    gateway.calls.clear()
    assert (await repair_browser_policy(gateway, expected_hash='hash-before'))['status'] == 'unchanged'
    assert len(gateway.calls) == 1


@pytest.mark.anyio
async def test_readback_mismatch_never_reports_repaired(config):
    gateway = FakeGateway(config, drift=True)
    with pytest.raises(AgentSkillGatewayError, match='verification failed'):
        await repair_browser_policy(gateway, expected_hash='hash-before')


@pytest.mark.anyio
async def test_unknown_patch_outcome_never_retries_or_rolls_back(config):
    gateway = FakeGateway(config, uncertain=True)
    with pytest.raises(TimeoutError):
        await repair_browser_policy(gateway, expected_hash='hash-before')
    assert [method for method, _ in gateway.calls] == ['config.get', 'config.patch']


def test_cli_defaults_to_preview_and_redacts_upstream_failure(tmp_path, monkeypatch, capsys, config):
    gateway = FakeGateway(config)
    monkeypatch.setattr(cli, 'AgentSkillGateway', lambda *_: gateway)
    assert cli.main(['--data-dir', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'preview'
    async def fail(*args, **kwargs):
        raise RuntimeError('raw-upstream-secret')
    monkeypatch.setattr(gateway, '_session', fail)
    assert cli.main(['--data-dir', str(tmp_path)]) == 1
    assert 'raw-upstream-secret' not in capsys.readouterr().out


@pytest.mark.parametrize('flags', [['--apply'], ['--expected-hash', 'hash']])
def test_cli_requires_both_explicit_apply_and_preview_hash(tmp_path, monkeypatch, flags):
    monkeypatch.setattr(cli, 'AgentSkillGateway', lambda *_: pytest.fail('must not connect'))
    with pytest.raises(SystemExit):
        cli.main(['--data-dir', str(tmp_path), *flags])
