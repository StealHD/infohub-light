import asyncio
from contextlib import asynccontextmanager
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.openclaw_browser_egress import install, launch, proxy


@pytest.mark.parametrize('address', [
    '127.0.0.1', '127.2.3.4', '10.0.0.1', '172.16.1.2', '192.168.1.1', '169.254.169.254',
    '0.0.0.0', '100.64.0.1', '198.18.0.1', '192.0.2.1', '224.0.0.1', '255.255.255.255',
    '192.0.0.8', '192.88.99.1',
    '::1', '::ffff:127.0.0.1', '2002:7f00:1::', '2606:4700:4700::1111',
])
def test_only_public_ipv4_can_be_upstream_targets(address):
    assert not proxy.public_ipv4(address)
    assert proxy.public_ipv4('1.1.1.1')


@pytest.mark.parametrize('line', [
    'GET http://example.com/ HTTP/1.1', 'CONNECT example.com:80 HTTP/1.1',
    'CONNECT user:password@example.com:443 HTTP/1.1', 'CONNECT [::1]:443 HTTP/1.1',
    'CONNECT example.com:443 HTTP/2', 'CONNECT example.com:443 extra HTTP/1.1',
    'CONNECT example.com/path:443 HTTP/1.1',
])
def test_proxy_refuses_http_credentials_and_invalid_authorities(line):
    with pytest.raises(ValueError):
        proxy.destination((line + '\r\n\r\n').encode())


@pytest.mark.anyio
async def test_mixed_public_private_dns_is_rejected(monkeypatch):
    lookup = AsyncMock(return_value=[(socket.AF_INET, 1, 6, '', (ip, 443))
                                    for ip in ('1.1.1.1', '127.0.0.1')])
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', lookup)
    with pytest.raises(ValueError, match='Non-public'):
        await proxy.resolve_public('example.com')


@asynccontextmanager
async def listening(handler):
    server = await asyncio.start_server(handler, '127.0.0.1', 0, limit=8192)
    async with server:
        yield server.sockets[0].getsockname()[1]


@pytest.mark.anyio
async def test_proxy_pins_dns_before_upstream_and_tunnels_without_reresolution():
    requests = []
    async def upstream(reader, writer):
        requests.append(await reader.readuntil(b'\r\n\r\n'))
        writer.write(b'HTTP/1.1 200 OK\r\n\r\n')
        await writer.drain()
        data = await reader.readexactly(4)
        writer.write(data)
        await writer.drain()
        writer.close()
    resolver = AsyncMock(return_value='1.1.1.1')
    async with listening(upstream) as upstream_port:
        service = proxy.PublicProxy(upstream_port, resolver=resolver)
        async with listening(service.connect) as port:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(b'CONNECT example.com:443 HTTP/1.1\r\nHost: malicious.invalid\r\n\r\n')
            await writer.drain()
            assert b'200' in await reader.readuntil(b'\r\n\r\n')
            writer.write(b'ping')
            await writer.drain()
            assert await reader.readexactly(4) == b'ping'
            writer.close()
            await writer.wait_closed()
    resolver.assert_awaited_once_with('example.com')
    assert requests == [b'CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n']


@pytest.mark.anyio
async def test_private_target_never_reaches_upstream():
    reached = []
    async def upstream(reader, writer):
        reached.append(True)
        writer.close()
    async with listening(upstream) as upstream_port:
        service = proxy.PublicProxy(upstream_port, resolver=AsyncMock(return_value='127.0.0.1'))
        async with listening(service.connect) as port:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(b'CONNECT localhost:443 HTTP/1.1\r\n\r\n')
            await writer.drain()
            assert b'403 Forbidden' in await reader.readuntil(b'\r\n\r\n')
            writer.close()
            await writer.wait_closed()
    assert reached == []


def test_launcher_drops_identity_and_environment_and_cannot_accept_proxy_override(monkeypatch, tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"proxy_port":18890,"cdp_port":18802}')
    monkeypatch.setattr(launch, 'CONFIG', config)
    monkeypatch.setattr(launch.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(launch.pwd, 'getpwnam', lambda _: SimpleNamespace(pw_uid=998, pw_gid=997, pw_dir=str(tmp_path)))
    events = []
    monkeypatch.setattr(launch, 'enforce_firewall', lambda *args: events.append(('firewall', args)))
    monkeypatch.setattr(launch.subprocess, 'run', lambda *args, **kwargs: None)
    for name in ('setgroups', 'setgid', 'setuid', 'chdir', 'umask'):
        monkeypatch.setattr(launch.os, name, lambda value, name=name: events.append((name, value)))
    monkeypatch.setattr(launch.os, 'execve', lambda *args: events.append(('exec', args)))
    monkeypatch.setattr(launch.sys, 'argv', ['launcher', '--remote-debugging-port=18802',
                                          '--proxy-server=http://evil.invalid', '--no-sandbox'])
    launch.main()
    assert events[:4] == [('firewall', (998, 18890)), ('setgroups', []), ('setgid', 997), ('setuid', 998)]
    executable, args, env = events[-1][1]
    assert executable == '/usr/bin/google-chrome-stable'
    assert '--proxy-server=http://127.0.0.1:18890' in args
    assert '--no-sandbox' not in args and not any('evil' in value for value in args)
    assert set(env) == {'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG'}


def test_firewall_is_scoped_to_dedicated_uid_with_no_global_flush():
    rules = launch.firewall_rules(998, 18890, replace=True)
    assert rules.startswith('delete table inet inteliscope_browser\n')
    assert 'flush ruleset' not in rules
    assert 'meta skuid 998 ip daddr 127.0.0.1 tcp dport 18890 accept' in rules
    assert 'meta skuid 998 counter reject' in rules
    with pytest.raises(ValueError):
        launch.firewall_rules(0, 18890, replace=False)


def test_install_artifacts_keep_owner_browser_and_gateway_config_untouched():
    files = install.files_for('ubuntu', 18890, 7890, 18802)
    assert not any('.openclaw' in path for path in files)
    proxy_unit = files['/etc/systemd/system/inteliscope-browser-egress.service'][0].decode()
    assert 'Requires=inteliscope-browser-firewall.service' in proxy_unit
    assert '--port 18890 --upstream-port 7890' in proxy_unit
    assert 'User=nobody' in proxy_unit and 'NoNewPrivileges=true' in proxy_unit
    browser_unit = files['/etc/systemd/system/inteliscope-managed-browser.service'][0].decode()
    assert 'Requires=inteliscope-browser-egress.service' in browser_unit
    assert f'ExecStart={install.LAUNCH} --remote-debugging-port=18802' in browser_unit
    assert 'KillMode=control-group' in browser_unit
    assert files[install.LAUNCH][0].startswith(b'#!/usr/bin/python3')
