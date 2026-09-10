"""Operator-only user service installer; does not start workers or change claim mode."""
import argparse
import os
from pathlib import Path
import subprocess
import uuid


def unit(deployment):
    # systemd specifier/argument expansion is not a path interpolation language.
    if any(char in str(deployment) for char in '\n\r\t"%\\ '):
        raise ValueError('Unsupported deployment path')
    return f'''[Unit]
Description=Inteliscope managed analysis supervisor
After=network-online.target openclaw-gateway.service

[Service]
Type=simple
WorkingDirectory={deployment}
ExecStart={deployment}/.venv/bin/python -m scripts.run_managed_analysis {deployment}/host.env
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
TimeoutStopSec=90
KillMode=control-group

[Install]
WantedBy=default.target
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deployment', required=True)
    args = parser.parse_args()
    deployment = Path(args.deployment)
    if not deployment.is_absolute() or deployment.resolve() != deployment:
        raise ValueError('Canonical deployment required')
    for relative in ('host.env', '.venv/bin/python', 'scripts/run_managed_analysis.py'):
        if not (deployment / relative).is_file():
            raise ValueError('Incomplete deployment')
    if (deployment / 'host.env').is_symlink() or (deployment / 'host.env').stat().st_mode & 0o077:
        raise ValueError('Private settings required')
    directory = Path.home() / '.config/systemd/user'
    if directory.resolve() != directory:
        raise ValueError('Unsafe user service directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / 'inteliscope-analysis.service'
    if target.is_symlink():
        raise ValueError('Unsafe service file')
    if target.exists():
        before = target.read_bytes()
        backup = deployment / ('analysis-service-before-' + uuid.uuid4().hex)
        backup.touch(mode=0o600, exist_ok=False)
        backup.write_bytes(before)
    temporary = directory / ('.inteliscope-analysis-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(unit(deployment))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Installed, not started. Review catalog-only mode and backlog before enabling claims.')


if __name__ == '__main__':
    main()
