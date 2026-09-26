#!/usr/bin/python3
"""Root-owned launcher: enforce dedicated browser egress, then drop all privileges."""
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys

CONFIG = Path('/etc/inteliscope/browser-egress.json')
TABLE = 'inteliscope_browser'
ACCOUNT = 'inteliscope-browser'


def firewall_rules(uid, port, *, replace):
    if uid < 100 or not 1024 <= port <= 65535:
        raise ValueError('Invalid browser identity or proxy port')
    remove = f'delete table inet {TABLE}\n' if replace else ''
    return remove + f'''table inet {TABLE} {{
 chain output {{
  type filter hook output priority -10; policy accept;
  meta skuid {uid} ct state established,related accept
  meta skuid {uid} ip daddr 127.0.0.1 tcp dport {port} accept
  meta skuid {uid} counter reject
 }}
}}
'''


def enforce_firewall(uid, port):
    present = subprocess.run(['/usr/sbin/nft', 'list', 'table', 'inet', TABLE],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    # A single nft transaction replaces only our table; other services are untouched.
    subprocess.run(['/usr/sbin/nft', '-f', '-'], input=firewall_rules(uid, port, replace=present),
                   text=True, check=True)


def chrome_arguments(cdp_port, proxy_port, home):
    return ['/usr/bin/google-chrome-stable', '--headless=new', '--no-first-run',
            '--no-default-browser-check', '--disable-dev-shm-usage', '--disable-quic',
            '--disable-background-networking', '--remote-debugging-address=127.0.0.1',
            f'--remote-debugging-port={cdp_port}', f'--user-data-dir={home}/profile',
            f'--proxy-server=http://127.0.0.1:{proxy_port}', '--proxy-bypass-list=<-loopback>',
            'about:blank']


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root-owned launcher must be invoked through its sudo rule')
    config = json.loads(CONFIG.read_text())
    account = pwd.getpwnam(ACCOUNT)
    enforce_firewall(account.pw_uid, config['proxy_port'])
    if sys.argv[1:] == ['--firewall-only']:
        return
    subprocess.run(['systemctl', 'is-active', '--quiet', 'inteliscope-browser-egress.service'], check=True)
    # Ignore caller-supplied Chrome flags, executable paths and profile paths. The
    # managed Gateway expects this configured port, but cannot select another one.
    ports = [arg for arg in sys.argv[1:] if arg.startswith('--remote-debugging-port=')]
    if ports != [f"--remote-debugging-port={config['cdp_port']}"]:
        raise SystemExit('Unexpected managed browser port')
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.chdir(account.pw_dir)
    os.umask(0o077)
    env = {'HOME': account.pw_dir, 'USER': ACCOUNT, 'LOGNAME': ACCOUNT,
           'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    arguments = chrome_arguments(config['cdp_port'], config['proxy_port'], account.pw_dir)
    os.execve(arguments[0], arguments, env)


if __name__ == '__main__':
    main()
