"""Select the deployment adapter without accepting browser host or path inputs."""
import os
from .managed_host import ManagedHost as LocalHost
from .cleanup_host import CleanupHost as LocalCleanupHost
from .manifest import digest


def ManagedHost(context):
    if os.getenv('HORIZON_OPENCLAW_MANAGED_TRANSPORT', 'local') == 'ssh':
        from .ssh_host import SSHHost
        return SSHHost(context)
    if os.getenv('HORIZON_OPENCLAW_MANAGED_TRANSPORT', 'local') != 'local':
        raise ValueError('Unsupported managed transport')
    return LocalHost(context)


def CleanupHost(context):
    if os.getenv('HORIZON_OPENCLAW_MANAGED_TRANSPORT', 'local') == 'local':
        return LocalCleanupHost(context)
    return ManagedHost(context)


def installation_digest(value):
    from .ssh_host import VerifiedInstallation
    return value.config_sha256 if isinstance(value, VerifiedInstallation) else digest(value)
