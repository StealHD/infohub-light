#!/usr/bin/python3
"""Install isolated managed-browser egress on the Gateway host; default is preview."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tempfile

HOME = '/var/lib/inteliscope-browser'
ACCOUNT = 'inteliscope-browser'
LAUNCH = '/usr/local/libexec/inteliscope-browser-launch'
PROXY = '/usr/local/libexec/inteliscope-browser-proxy.py'
WRAPPER = '/usr/local/bin/inteliscope-managed-chrome'


def unit_files(proxy_port, upstream_port, cdp_port):
    return {
        'inteliscope-browser-firewall.service': f'''[Unit]
Description=Inteliscope managed browser egress firewall
Before=inteliscope-browser-egress.service
[Service]
Type=oneshot
ExecStart={LAUNCH} --firewall-only
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
''',
        'inteliscope-managed-browser.service': f'''[Unit]
Description=Inteliscope isolated managed Chrome
Requires=inteliscope-browser-egress.service
After=inteliscope-browser-egress.service
[Service]
ExecStart={LAUNCH} --remote-debugging-port={cdp_port}
Restart=on-failure
RestartSec=3
KillMode=control-group
TimeoutStopSec=15
MemoryMax=768M
TasksMax=128
[Install]
WantedBy=multi-user.target
''',
        'inteliscope-browser-egress.service': f'''[Unit]
Description=Inteliscope public HTTPS browser proxy
Requires=inteliscope-browser-firewall.service
After=inteliscope-browser-firewall.service network.target
[Service]
User=nobody
Group=nogroup
ExecStart=/usr/bin/python3 {PROXY} --port {proxy_port} --upstream-port {upstream_port}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=128M
TasksMax=32
LimitNOFILE=512
[Install]
WantedBy=multi-user.target
''',
    }


def files_for(gateway_user, proxy_port, upstream_port, cdp_port):
    base = Path(__file__).resolve().parent
    result = {
        LAUNCH: (base.joinpath('launch.py').read_bytes(), 0o755),
        PROXY: (base.joinpath('proxy.py').read_bytes(), 0o644),
        WRAPPER: (f'#!/bin/sh\nexec /usr/bin/sudo -n -- {LAUNCH} "$@"\n'.encode(), 0o755),
        '/etc/inteliscope/browser-egress.json': (json.dumps({
            'proxy_port': proxy_port, 'cdp_port': cdp_port, 'upstream_port': upstream_port,
        }).encode(), 0o644),
        '/etc/sudoers.d/inteliscope-managed-browser': (
            f'{gateway_user} ALL=(root) NOPASSWD: {LAUNCH}\n'.encode(), 0o440),
    }
    result.update({f'/etc/systemd/system/{name}': (text.encode(), 0o644)
                   for name, text in unit_files(proxy_port, upstream_port, cdp_port).items()})
    return result


def write_root_file(name, content, mode):
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Refusing symlink installation path')
    descriptor, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
        if name.startswith('/etc/sudoers.d/'):
            subprocess.run(['/usr/sbin/visudo', '-cf', temp], check=True, stdout=subprocess.DEVNULL)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(files):
    if os.geteuid() != 0:
        raise ValueError('Apply requires root')
    for program in ('/usr/sbin/nft', '/usr/bin/google-chrome-stable', '/usr/bin/python3',
                    '/usr/bin/sudo', '/usr/sbin/visudo'):
        if not os.access(program, os.X_OK):
            raise ValueError('Required host executable unavailable')
    try:
        account = pwd.getpwnam(ACCOUNT)
    except KeyError:
        subprocess.run(['useradd', '--system', '--create-home', '--home-dir', HOME,
                        '--shell', '/usr/sbin/nologin', ACCOUNT], check=True)
        account = pwd.getpwnam(ACCOUNT)
    if account.pw_uid < 100 or account.pw_dir != HOME or account.pw_shell != '/usr/sbin/nologin':
        raise ValueError('Unexpected existing browser account')
    os.chmod(HOME, 0o700)
    # Save only our own prior installation files; no Gateway secrets/config are copied.
    backup = Path(tempfile.mkdtemp(prefix='browser-egress-', dir='/var/backups'))
    manifest = {}
    for index, (name, (content, mode)) in enumerate(files.items()):
        path = Path(name)
        if path.is_symlink():
            raise ValueError('Refusing symlink installation path')
        if path.exists():
            shutil.copy2(path, backup / str(index))
        manifest[name] = str(index) if path.exists() else None
        (backup / 'manifest.json').write_text(json.dumps(manifest))
        write_root_file(name, content, mode)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', 'inteliscope-browser-firewall.service',
                    'inteliscope-browser-egress.service', 'inteliscope-managed-browser.service'],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['systemctl', 'restart', 'inteliscope-browser-firewall.service',
                    'inteliscope-browser-egress.service', 'inteliscope-managed-browser.service'], check=True)
    subprocess.run(['systemctl', 'is-active', '--quiet', 'inteliscope-managed-browser.service'], check=True)
    return str(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-user', required=True)
    parser.add_argument('--proxy-port', type=int, default=18890)
    parser.add_argument('--upstream-port', type=int, default=7890)
    parser.add_argument('--cdp-port', type=int, default=18800)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', args.gateway_user):
        parser.error('Invalid Gateway account')
    if pwd.getpwnam(args.gateway_user).pw_uid == 0:
        parser.error('Gateway must use an unprivileged account')
    ports = (args.proxy_port, args.upstream_port, args.cdp_port)
    if len(set(ports)) != 3 or any(not 1024 <= port <= 65535 for port in ports):
        parser.error('Three distinct unprivileged ports required')
    files = files_for(args.gateway_user, *ports)
    result = {'status': 'preview', 'wrapper': WRAPPER,
              'files': {path: hashlib.sha256(data).hexdigest() for path, (data, _) in files.items()}}
    if args.apply:
        result.update(status='installed', backup=install(files))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
