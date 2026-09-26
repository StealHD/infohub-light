"""Explicit operator repair of a managed browser's loopback CDP policy conflict."""
from copy import deepcopy
import json
from urllib.parse import urlsplit

from ..agent_skill_gateway import AgentSkillGatewayError

_LOOPBACK = {'localhost', '127.0.0.1', '::1', '[::1]', '*.localhost'}
_FLAGS = {'dangerouslyAllowPrivateNetwork', 'allowPrivateNetwork'}
_LISTS = {'blockedHostnames', 'allowedHostnames', 'allowedOrigins', 'hostnameAllowlist'}


def _managed_profiles(browser):
    if not isinstance(browser, dict):
        raise ValueError('browser_policy_unsupported')
    profiles = browser.get('profiles', {})
    if not isinstance(profiles, dict) or browser.get('enabled') is not True:
        raise ValueError('browser_policy_unsupported')
    if browser.get('defaultProfile', 'openclaw') not in {'openclaw', *profiles}:
        raise ValueError('browser_policy_unsupported')
    for profile in [browser, *profiles.values()]:
        if not isinstance(profile, dict) or profile.get('attachOnly') is True:
            raise ValueError('browser_policy_unsupported')
        if profile.get('driver', 'openclaw') != 'openclaw':
            raise ValueError('browser_policy_unsupported')
        if 'cdpUrl' in profile:
            if not isinstance(profile['cdpUrl'], str):
                raise ValueError('browser_policy_unsupported')
            url = urlsplit(profile['cdpUrl'])
            if (url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1', '::1'}
                    or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
                raise ValueError('browser_policy_unsupported')


def repaired_browser_policy(config):
    """Public-web-only repair; custom trust grants/remote profiles need manual review."""
    browser = config.get('browser', {})
    _managed_profiles(browser)
    policy = browser.get('ssrfPolicy', {})
    if not isinstance(policy, dict) or set(policy) - (_FLAGS | _LISTS):
        raise ValueError('browser_policy_unsupported')
    for key, value in policy.items():
        if key in _FLAGS and type(value) is not bool:
            raise ValueError('browser_policy_unsupported')
        if key in _LISTS and (not isinstance(value, list) or any(not isinstance(v, str) for v in value)):
            raise ValueError('browser_policy_unsupported')
    if any(policy.get(key) for key in _LISTS - {'blockedHostnames'}):
        raise ValueError('browser_policy_custom_trust')
    blocked = policy.get('blockedHostnames', [])
    kept = [host for host in blocked if host.strip().lower().rstrip('.') not in _LOOPBACK]
    if kept == blocked:
        return deepcopy(policy)
    for host in kept:
        pattern = host.strip().lower().rstrip('.')
        if pattern.startswith('*.') and any(value.endswith(pattern[1:]) for value in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('browser_policy_custom_trust')
    # Never merely remove loopback blocks while retaining the private-network bypass.
    result = {**deepcopy(policy), 'dangerouslyAllowPrivateNetwork': False, 'blockedHostnames': kept}
    if 'allowPrivateNetwork' in result:
        result['allowPrivateNetwork'] = False
    return result


async def repair_browser_policy(gateway, *, expected_hash=None):
    """Read-only by default; explicit CAS apply makes one patch, never restarts or retries."""
    async def operation(socket, hello):
        methods = hello.get('features', {}).get('methods', [])
        required = {'config.get', 'config.patch'} if expected_hash else {'config.get'}
        if not required.issubset(methods):
            raise AgentSkillGatewayError('Browser policy configuration is unavailable')
        current = await gateway._request(socket, 'browser-policy-get', 'config.get', {})
        config, base_hash = current.get('config'), current.get('hash')
        if not isinstance(config, dict) or not isinstance(base_hash, str) or not base_hash:
            raise AgentSkillGatewayError('Browser policy configuration is unavailable')
        if expected_hash is not None and expected_hash != base_hash:
            raise ValueError('browser_policy_conflict')
        target = repaired_browser_policy(config)
        previous = config['browser'].get('ssrfPolicy', {})
        changed = target != previous
        result = {'status': 'preview' if changed else 'unchanged', 'base_hash': base_hash,
                  'changed': changed, 'private_navigation_disabled': (
                      target.get('dangerouslyAllowPrivateNetwork') is False and target.get('allowPrivateNetwork', False) is False),
                  'removed_loopback_blocks': len(previous.get('blockedHostnames', [])) - len(target.get('blockedHostnames', []))}
        if not changed or expected_hash is None:
            return result
        await gateway._request(socket, 'browser-policy-patch', 'config.patch', {
            'baseHash': base_hash, 'raw': json.dumps({'browser': {'ssrfPolicy': target}}),
            'replacePaths': ['browser.ssrfPolicy.blockedHostnames'],
            'note': 'Repair managed browser CDP policy; restrict navigation to public destinations',
        })
        verified = await gateway._request(socket, 'browser-policy-verify', 'config.get', {})
        expected_browser = {**config['browser'], 'ssrfPolicy': target}
        if verified.get('config', {}).get('browser') != expected_browser:
            raise AgentSkillGatewayError('Browser policy verification failed; inspect before retrying')
        loaded = (bool(verified.get('configRevisionHash'))
                  and verified.get('appliedConfigHash') == verified['configRevisionHash'])
        return {**result, 'status': 'applied' if loaded else 'saved_pending_reload'}
    return await gateway._session(operation)
