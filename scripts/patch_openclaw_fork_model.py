"""Explicit, version-bounded Gateway repair; never invoked by Service or setup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

ANCHOR = '\t\t\tconst childModel = resolveSessionModelRef(params.cfg, entry, target.agentId);'
MARKER = '// inteliscope: explicit fork model v1'
PIN = '''
\t\t\t// inteliscope: explicit fork model v1
\t\t\tif (normalizeOptionalString(params.model)) {
\t\t\t\tentry.providerOverride = childModel.provider;
\t\t\t\tentry.modelOverride = childModel.model;
\t\t\t\tentry.modelOverrideSource = "user";
\t\t\t\tentry.modelOverrideRouteResolution = "resolved";
\t\t\t}'''


def patched_source(source):
    if source.count(ANCHOR) != 1:
        raise ValueError('Unsupported Gateway fork implementation; no changes made.')
    if MARKER in source:
        if source.count(MARKER) != 1 or ANCHOR + PIN not in source:
            raise ValueError('Unexpected existing patch; no changes made.')
        return source
    # This anchor is after the non-fork return and before transcript forking.
    if 'if (params.fork !== true)' not in source or 'const forkParentSessionKey = canonicalParentSessionKey;' not in source:
        raise ValueError('Unsupported Gateway fork boundaries; no changes made.')
    return source.replace(ANCHOR, ANCHOR + PIN)


def patch_package(package, apply=False):
    package = Path(package).resolve()
    metadata = json.loads((package / 'package.json').read_text())
    if metadata.get('name') != 'openclaw' or metadata.get('version') not in {'2026.9.2', '2026.9.3'}:
        raise ValueError('Only reviewed OpenClaw 2026.9.2/2026.9.3 packages are supported.')
    candidates = sorted(p for p in (package / 'dist').glob('session-create-service-*') if p.suffix in {'.js', '.mjs'} and ANCHOR in p.read_text())
    if len(candidates) != 1:
        raise ValueError('Expected exactly one session-create implementation.')
    target = candidates[0]
    original = target.read_bytes()
    patched = patched_source(original.decode()).encode()
    digest = hashlib.sha256(original).hexdigest()
    status = 'already_patched' if patched == original else 'ready'
    if apply and patched != original:
        backup = target.with_name(target.name + '.inteliscope-' + digest[:12] + '.bak')
        with backup.open('xb') as stream:
            os.chmod(backup, 0o600)
            stream.write(original)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.fork-model-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(patched)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, target.stat().st_mode & 0o777)
            if target.read_bytes() != original:
                raise ValueError('Package changed during patch; refusing overwrite.')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        status = 'patched_restart_required'
    return {'status': status, 'version': metadata['version'], 'path': str(target), 'original_sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', required=True)
    parser.add_argument('--apply', action='store_true', help='Write the reviewed patch and a private backup; does not restart Gateway.')
    args = parser.parse_args()
    print(json.dumps(patch_package(args.package_root, args.apply)))
